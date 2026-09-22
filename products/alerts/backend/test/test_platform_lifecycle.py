from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.alerts.backend.facade.contracts import AlertEventKind, PlatformAlertOutcome, SourceKind
from products.alerts.backend.facade.platform_alerts import due_checks, record_outcomes
from products.alerts.backend.models import PlatformAlertConfiguration, PlatformAlertEvent


class TestPlatformAlertLifecycle(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.cutoff = datetime(2026, 9, 16, 10, tzinfo=UTC)
        with team_scope(self.team.id):
            self.configuration = PlatformAlertConfiguration.objects.create(
                team=self.team,
                name="API errors",
                source_kind=PlatformAlertConfiguration.SourceKind.LOGS,
                source_config={},
                threshold_count=10,
                threshold_operator="above",
                window_minutes=5,
                check_interval_minutes=10,
                next_check_at=self.cutoff - timedelta(minutes=1),
            )
        self.slot = (self.cutoff - timedelta(minutes=1)).isoformat()

    def _record(self, now: datetime | None = None, **overrides) -> None:
        moment = now or self.cutoff
        fields = {
            "configuration_id": self.configuration.id,
            "evaluation_key": f"window:{moment.isoformat()}",
            "kind": AlertEventKind.FIRING,
            "new_state": "firing",
            "notified": True,
            "consecutive_failures": 0,
        }
        fields.update(overrides)
        record_outcomes(self.team.id, [PlatformAlertOutcome(**fields)], moment, team_timezone=self.team.timezone)

    def _events(self) -> list[PlatformAlertEvent]:
        with team_scope(self.team.id):
            return list(PlatformAlertEvent.objects.filter(alert__configuration=self.configuration))

    def test_a_disabling_outcome_stops_the_configuration_being_discovered(self) -> None:
        self._record(new_state="broken", notified=False, consecutive_failures=5, disable=True)

        with team_scope(self.team.id):
            self.configuration.refresh_from_db()
        assert self.configuration.enabled is False
        assert due_checks(self.team.id, SourceKind.LOGS.value, self.slot, self.cutoff + timedelta(hours=1)) == ()

    def test_recording_a_batch_twice_advances_the_schedule_once(self) -> None:
        self._record()
        with team_scope(self.team.id):
            self.configuration.refresh_from_db()
        after_first = self.configuration.next_check_at

        self._record()

        # Advancing twice skips a whole cycle for every alert in the batch.
        with team_scope(self.team.id):
            self.configuration.refresh_from_db()
        assert self.configuration.next_check_at == after_first
        # A second row for one evaluation double-counts the alert in any history reading it.
        assert len(self._events()) == 1

    @parameterized.expand([("off", False, 0), ("on", True, 1)])
    def test_a_check_that_moved_nothing_is_kept_only_under_comparison(
        self, _name: str, record_every_check: bool, expected_rows: int
    ) -> None:
        with team_scope(self.team.id):
            PlatformAlertConfiguration.objects.filter(id=self.configuration.id).update(
                record_every_check=record_every_check
            )

        self._record(kind=AlertEventKind.CHECK, new_state="not_firing", notified=False)

        # Off, a one-minute alert would mint about 43,000 rows a month that nothing reads.
        # On, the comparison cohort has no data at all without them.
        assert len(self._events()) == expected_rows

    def test_a_state_change_nobody_was_notified_of_is_still_recorded(self) -> None:
        self._record(kind=AlertEventKind.FIRING, new_state="firing", notified=True)
        # A cooldown suppresses the notification while the alert still moves. Keying retention
        # on the notification alone would lose the move, which is the thing history is for.
        self._record(
            now=self.cutoff + timedelta(minutes=10),
            kind=AlertEventKind.CHECK,
            new_state="not_firing",
            notified=False,
        )

        events = sorted(self._events(), key=lambda event: event.occurred_at)
        assert [(e.previous_state, e.state) for e in events] == [
            ("not_firing", "firing"),
            ("firing", "not_firing"),
        ]

    def test_a_recorded_check_carries_what_it_was_evaluated_against(self) -> None:
        self._record(value=42.0, query_duration_ms=17)

        # Without the snapshot a retried delivery renders the message against a threshold the
        # check never saw, and a comparison has no bound to line the two stacks up on.
        event = self._events()[0]
        assert event.value == 42.0
        assert event.query_duration_ms == 17
        assert event.condition_snapshot["threshold_count"] == 10
        assert event.condition_snapshot["threshold_operator"] == "above"


class TestAlertEventKindVocabulary(SimpleTestCase):
    """Two enums, no database."""

    def test_the_contract_and_the_column_name_the_same_kinds(self) -> None:
        # Django does not check `choices` on save, so a kind added to one and not the other
        # writes a value no reader recognizes, silently.
        assert {k.value for k in AlertEventKind} == set(PlatformAlertEvent.Kind.values)
