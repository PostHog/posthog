import contextlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.alerts_platform.backend.facade.appearance import record_occurrence
from products.alerts_platform.backend.facade.contracts import (
    APPEARANCE_DETAIL_KEY,
    APPEARANCE_GROUPING,
    AlertEventKind,
    OccurrenceFeed,
    OccurrenceKind,
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
        # The longest span the feed can read, as a ClickHouse scan budget limits a busy project's reads.
        self.max_read_span: timedelta | None = None
        feed = OccurrenceFeed(
            ready_until=lambda team_id, now: now - timedelta(minutes=5),
            seen=self._feed_seen,
            seed_lookback=timedelta(days=1),
        )
        patcher = patch.dict(occurrences._feeds, {SOURCE: feed})
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

    def _feed_seen(self, team_id: int, since: datetime, until: datetime, limit: int) -> list[SeenIdentity]:
        if self.max_read_span is not None and until - since > self.max_read_span:
            raise TimeoutError("Over the scan budget")
        return [s for s in self.sightings if since <= s.seen_at < until][:limit]

    def _register(self, now: datetime) -> None:
        # The registrar runs on its own schedule, and stamps what it records with the clock.
        with time_machine.travel(now, tick=False):
            occurrences.store_for(SOURCE).catch_up(team_id=self.team.id, now=now, budget=timedelta(seconds=60))

    def _tick(self, now: datetime):
        # The registry stamps what it records with the clock, so the clock is the check's own time.
        with time_machine.travel(now, tick=False):
            self.configuration.refresh_from_db()
            evaluation = evaluate_appearance_batch(
                SOURCE, self.team.id, slot_of(self.configuration.next_check_at, now), now
            )
            record_outcomes(self.team.id, evaluation.outcomes, now)
        (outcome,) = evaluation.outcomes
        return outcome, evaluation.deliveries

    def _record_then_tick(self, now: datetime):
        # A fact the registrar records is read by the next check, a minute later.
        self._register(now)
        return self._tick(now + timedelta(minutes=1))

    def test_announces_each_identity_once_and_again_when_it_comes_back_after_a_resolve(self) -> None:
        self.sightings = [
            _seen("known", T0 - timedelta(hours=2)),
            _seen("fresh", T0 + timedelta(minutes=10)),
            _seen("other-service", T0 + timedelta(minutes=10), service="web"),
        ]

        outcome, deliveries = self._record_then_tick(T0 + timedelta(minutes=20))
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
        outcome, _ = self._record_then_tick(T0 + timedelta(minutes=50))
        (group,) = outcome.groups
        assert group.source_detail[APPEARANCE_DETAIL_KEY] == "reappeared"
        # It is described as it came back, not as it was first seen.
        assert group.labels["release"] == "v2"
        # A reappearance threads under the message that announced the identity.
        assert group.firing_episode is not None and group.firing_episode.started_at == T0 + timedelta(minutes=10)

    def test_a_feed_read_too_large_to_finish_shortens_the_registrar_s_next_read_until_it_catches_up(self) -> None:
        self.sightings = [_seen("fresh", T0 + timedelta(minutes=10))]
        self.max_read_span = timedelta(hours=7)
        now = T0 + timedelta(minutes=20)

        for _ in range(5):
            # A run raises at the read that fails, and keeps the spans it recorded before it.
            with contextlib.suppress(TimeoutError):
                self._register(now)

        # The check reads only the registry, so a failing feed never fails it.
        outcome, deliveries = self._tick(now + timedelta(minutes=1))
        assert [group.grouping_key for group in outcome.groups] == ["fresh"]
        assert len(deliveries) == 1

    def test_a_late_check_in_quiet_hours_keeps_its_window_for_the_first_check_after_them(self) -> None:
        self.sightings = [_seen("fresh", T0 + timedelta(minutes=10))]
        PlatformAlertConfiguration.objects.for_team(self.team.id).filter(id=self.configuration.id).update(
            schedule_restriction={"blocked_windows": [{"start": "12:15", "end": "12:25"}]}
        )

        self._register(T0 + timedelta(minutes=20))
        held, _ = self._tick(T0 + timedelta(minutes=20))
        announced, deliveries = self._tick(T0 + timedelta(minutes=30))

        assert held.groups == ()
        assert [group.grouping_key for group in announced.groups] == ["fresh"]
        assert len(deliveries) == 1

    def test_a_pushed_fact_is_announced_once_even_when_it_arrives_after_its_window(self) -> None:
        late = T0 + timedelta(minutes=12)
        # Pushed at 12:21 about something that occurred at 12:12, after the check at 12:20 read up to 12:15.
        self._tick(T0 + timedelta(minutes=20))
        with time_machine.travel(T0 + timedelta(minutes=21), tick=False):
            for _ in range(2):
                record_occurrence(
                    SOURCE,
                    team_id=self.team.id,
                    identity_key="issue-1",
                    kind=OccurrenceKind.REAPPEARED,
                    occurred_at=late,
                    first_seen_at=T0 - timedelta(days=3),
                    labels={"service_name": "api"},
                )

        outcome, deliveries = self._tick(T0 + timedelta(minutes=30))
        again, _ = self._tick(T0 + timedelta(minutes=40))

        (group,) = outcome.groups
        assert (group.grouping_key, group.source_detail[APPEARANCE_DETAIL_KEY]) == ("issue-1", "reappeared")
        assert group.firing_episode is not None and group.firing_episode.started_at == T0 - timedelta(days=3)
        assert len(deliveries) == 1
        assert again.groups == ()
        # A reappearance from before a resolve is not news.
        occurrences.resolve(SOURCE, team_id=self.team.id, identity_key="issue-1", at=late + timedelta(minutes=1))
        assert record_occurrence(
            SOURCE,
            team_id=self.team.id,
            identity_key="issue-1",
            kind=OccurrenceKind.REAPPEARED,
            occurred_at=late + timedelta(seconds=30),
            first_seen_at=T0 - timedelta(days=3),
            labels={"service_name": "api"},
        )
        assert self._tick(T0 + timedelta(minutes=50))[0].groups == ()
        # A project with no appearance alert on a source records nothing for it.
        assert not record_occurrence(
            SourceKind.INSIGHT,
            team_id=self.team.id,
            identity_key="issue-1",
            kind=OccurrenceKind.NEW,
            occurred_at=late,
            first_seen_at=late,
            labels={},
        )

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

        outcome, deliveries = self._record_then_tick(T0 + timedelta(minutes=20))

        (group,) = outcome.groups
        assert (group.kind, group.notified) == (AlertEventKind.CHECK, False)
        assert deliveries == ()
