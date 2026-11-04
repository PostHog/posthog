from dataclasses import replace
from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.alerts_platform.backend.facade.contracts import (
    APPEARANCE_DETAIL_KEY,
    APPEARANCE_GROUPING,
    AlertEventKind,
    OccurrenceFeed,
    SeenIdentity,
    SourceKind,
)
from products.alerts_platform.backend.logic import occurrences
from products.alerts_platform.backend.logic.appearance import evaluate_appearance_batch
from products.alerts_platform.backend.logic.platform_lifecycle import record_outcomes, slot_of
from products.alerts_platform.backend.models import PlatformAlert, PlatformAlertConfiguration

SOURCE = SourceKind.METRICS
T0 = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def _seen(key: str, at: datetime, service: str = "api") -> SeenIdentity:
    return SeenIdentity(identity_key=key, seen_at=at, labels={"service_name": service})


class TestAppearanceAlerts(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.sightings: list[SeenIdentity] = []
        feed = OccurrenceFeed(
            ready_until=lambda team_id, now: now - timedelta(minutes=5),
            seen=lambda team_id, since, until, limit: [s for s in self.sightings if since <= s.seen_at < until][:limit],
            seed_lookback=timedelta(days=1),
        )
        patcher = patch.dict(occurrences._stores, {SOURCE: occurrences.RegistryStore(SOURCE, feed)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.configuration = PlatformAlertConfiguration.objects.for_team(self.team.id).create(
            team=self.team,
            name="New patterns",
            source_kind=SOURCE.value,
            source_config={"filters": [{"key": "service_name", "operator": "exact", "values": ["api"]}]},
            alert_kind=PlatformAlertConfiguration.Kind.APPEARANCE,
            grouping=APPEARANCE_GROUPING.to_stored(),
            check_interval_minutes=1,
            next_check_at=T0,
            owner=PlatformAlertConfiguration.Owner.PLATFORM,
            destinations_owner=PlatformAlertConfiguration.Owner.PLATFORM,
        )
        PlatformAlertConfiguration.objects.for_team(self.team.id).filter(id=self.configuration.id).update(created_at=T0)

    def _tick(self, now: datetime):
        self.configuration.refresh_from_db()
        evaluation = evaluate_appearance_batch(
            SOURCE, self.team.id, slot_of(self.configuration.next_check_at, now), now
        )
        record_outcomes(self.team.id, evaluation.outcomes, now)
        (outcome,) = evaluation.outcomes
        return outcome, evaluation.deliveries

    def test_announces_each_identity_once_and_again_when_it_comes_back_after_a_resolve(self) -> None:
        self.sightings = [
            _seen("known", T0 - timedelta(hours=2)),
            _seen("fresh", T0 + timedelta(minutes=10)),
            _seen("other-service", T0 + timedelta(minutes=10), service="web"),
        ]

        outcome, deliveries = self._tick(T0 + timedelta(minutes=20))
        (group,) = outcome.groups
        assert group.grouping_key == "fresh"
        assert group.kind == AlertEventKind.APPEARED
        assert group.firing_episode is not None and group.firing_episode.started_at == T0 + timedelta(minutes=10)
        assert group.source_detail[APPEARANCE_DETAIL_KEY] == "new"
        assert len(deliveries) == 1

        outcome, deliveries = self._tick(T0 + timedelta(minutes=30))
        assert outcome.groups == ()
        assert deliveries == ()

        # Resolved inside the window the registry has not read yet, and seen on both sides of it.
        occurrences.resolve(SOURCE, team_id=self.team.id, identity_key="fresh", at=T0 + timedelta(minutes=27))
        self.sightings.append(
            replace(
                _seen("fresh", T0 + timedelta(minutes=26)),
                last_seen_at=T0 + timedelta(minutes=40),
                labels={"service_name": "api", "release": "v2"},
            )
        )
        outcome, _ = self._tick(T0 + timedelta(minutes=50))
        (group,) = outcome.groups
        assert group.source_detail[APPEARANCE_DETAIL_KEY] == "reappeared"
        # It is described as it came back, not as it was first seen.
        assert group.labels["release"] == "v2"
        # A reappearance threads under the message that announced the identity.
        assert group.firing_episode is not None and group.firing_episode.started_at == T0 + timedelta(minutes=10)

    def test_a_late_check_in_quiet_hours_keeps_its_window_for_the_first_check_after_them(self) -> None:
        self.sightings = [_seen("fresh", T0 + timedelta(minutes=10))]
        PlatformAlertConfiguration.objects.for_team(self.team.id).filter(id=self.configuration.id).update(
            schedule_restriction={"blocked_windows": [{"start": "12:15", "end": "12:25"}]}
        )

        held, _ = self._tick(T0 + timedelta(minutes=20))
        announced, deliveries = self._tick(T0 + timedelta(minutes=30))

        assert held.groups == ()
        assert [group.grouping_key for group in announced.groups] == ["fresh"]
        assert len(deliveries) == 1

    @parameterized.expand(
        [
            ("alert_snoozed", "configuration"),
            ("identity_snoozed", "group"),
        ]
    )
    def test_a_muted_identity_is_recorded_without_a_message(self, _name: str, scope: str) -> None:
        self.sightings = [_seen("fresh", T0 + timedelta(minutes=10))]
        if scope == "configuration":
            PlatformAlertConfiguration.objects.for_team(self.team.id).filter(id=self.configuration.id).update(
                snooze_until=T0 + timedelta(days=1)
            )
        else:
            PlatformAlert.objects.for_team(self.team.id).create(
                configuration=self.configuration,
                team=self.team,
                grouping_key="fresh",
                snooze_until=T0 + timedelta(days=1),
            )

        outcome, deliveries = self._tick(T0 + timedelta(minutes=20))

        (group,) = outcome.groups
        assert (group.kind, group.notified) == (AlertEventKind.CHECK, False)
        assert deliveries == ()
