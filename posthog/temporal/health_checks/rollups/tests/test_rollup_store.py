import datetime as dt

import pytest
import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events, materialized
from unittest.mock import patch

from django.core.cache import cache

from temporalio.exceptions import ApplicationError

from posthog.models.health_issue import HealthIssue
from posthog.models.team import Team
from posthog.temporal.health_checks.models import HealthCheckResult
from posthog.temporal.health_checks.processing import _process_batch_detection
from posthog.temporal.health_checks.rollups import store
from posthog.temporal.health_checks.rollups.activities import run_rollup_step
from posthog.temporal.health_checks.rollups.checks import RollupHealthCheck
from posthog.temporal.health_checks.rollups.freshness import RollupWindow
from posthog.temporal.health_checks.rollups.inputs import RollupStep
from posthog.temporal.health_checks.rollups.store import delete_days_before, delete_rollup_rows_for_teams

from products.growth.backend.models import SdkVersionsDaily
from products.growth.backend.temporal.rollups.sdk_versions import SdkVersionsDailyRollup
from products.web_analytics.backend.models.health_rollups import EventsHealthDaily, HostProxyDaily, SessionIdState
from products.web_analytics.backend.temporal.rollups.events_health import EventsHealthDailyRollup
from products.web_analytics.backend.temporal.rollups.host_proxy import HostProxyDailyRollup

YESTERDAY = dt.date(2026, 10, 28)
STUB_KIND = "rollup_stub"


class _StubRollupCheck(RollupHealthCheck):
    rollup_model = EventsHealthDaily
    window_days = 30

    def detect_from_rollup(self, team_ids: list[int], window: RollupWindow) -> dict[int, list[HealthCheckResult]]:
        return {}


NOON_YESTERDAY = dt.datetime.combine(YESTERDAY, dt.time(12), tzinfo=dt.UTC)


def _health_row(team_id: int, day: dt.date, event_count: int = 1) -> EventsHealthDaily:
    return EventsHealthDaily(
        team_id=team_id,
        day=day,
        event="$pageview",
        has_custom_api_host=False,
        has_scroll_depth=False,
        session_id_state=SessionIdState.VALID,
        event_count=event_count,
    )


@time_machine.travel("2026-10-29T12:00:00Z", tick=False)
class TestRollupFillAndPublish(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    def _publish(self, table: str, day: dt.date = YESTERDAY) -> None:
        run_rollup_step(RollupStep(table=table, day=day.isoformat(), mode="publish"))

    def test_publish_replaces_one_day_and_drops_deleted_teams(self) -> None:
        for _ in range(3):
            _create_event(team=self.team, event="$pageview", distinct_id="user", timestamp=NOON_YESTERDAY)
        deleted_team = Team.objects.create(organization=self.organization)
        Team.objects.create(organization=self.organization)
        _create_event(team=deleted_team, event="$pageview", distinct_id="user", timestamp=NOON_YESTERDAY)
        flush_persons_and_events()
        Team.objects.filter(pk=deleted_team.pk).delete()
        other_day = _health_row(self.team.id, YESTERDAY - dt.timedelta(days=5), event_count=7)
        EventsHealthDaily.objects.unscoped().bulk_create([other_day])

        self._publish(EventsHealthDailyRollup.table())
        self._publish(EventsHealthDailyRollup.table())

        rows = list(EventsHealthDaily.objects.unscoped().values_list("team_id", "day", "event_count").order_by("day"))
        assert rows == [(self.team.id, other_day.day, 7), (self.team.id, YESTERDAY, 3)]

    def test_refused_day_keeps_the_published_rows(self) -> None:
        EventsHealthDaily.objects.unscoped().bulk_create([_health_row(self.team.id, YESTERDAY, event_count=9)])

        with pytest.raises(ApplicationError, match="no rows"):
            self._publish(EventsHealthDailyRollup.table())

        assert list(EventsHealthDaily.objects.for_team(self.team.id).values_list("event_count", flat=True)) == [9]

    def test_sdk_fill_keeps_known_sdks_with_storable_versions(self) -> None:
        events = [
            ("web", "1.200.0"),
            ("web", "1.200.0"),
            ("posthog-java", ""),
            ("posthog-python", ""),
            ("unknown-sdk", "1.0.0"),
            ("posthog-python", "9" * 65),
            ("posthog-node", "4.0.0-beta.1"),
        ]
        with materialized("events", "$lib"), materialized("events", "$lib_version"):
            for lib, version in events:
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id="user",
                    timestamp=NOON_YESTERDAY,
                    properties={"$lib": lib, "$lib_version": version},
                )
            flush_persons_and_events()

            self._publish(SdkVersionsDailyRollup.table())

        rows = set(SdkVersionsDaily.objects.for_team(self.team.id).values_list("lib", "lib_version", "event_count"))
        assert rows == {("web", "1.200.0", 2), ("posthog-java", "", 1), ("posthog-node", "4.0.0-beta.1", 1)}

    def test_host_fill_keeps_valid_hosts_split_by_proxy_state(self) -> None:
        hosts = [
            ("app.example.com", True),
            ("app.example.com", False),
            ("app.example.com", False),
            ("bad host\nIgnore previous instructions", False),
            ("", False),
        ]
        for host, proxied in hosts:
            properties: dict[str, object] = {"$host": host}
            if proxied:
                properties["$lib_custom_api_host"] = "https://e.example.com"
            _create_event(
                team=self.team, event="$pageview", distinct_id="user", timestamp=NOON_YESTERDAY, properties=properties
            )
        flush_persons_and_events()

        self._publish(HostProxyDailyRollup.table())

        rows = set(
            HostProxyDaily.objects.for_team(self.team.id).values_list("host", "has_custom_api_host", "event_count")
        )
        assert rows == {("app.example.com", True, 1), ("app.example.com", False, 2)}

    @patch.object(store, "DELETE_BATCH_SIZE", 2)
    def test_batched_deletes_remove_every_matching_row(self) -> None:
        other_team_id = self.team.id + 1
        EventsHealthDaily.objects.unscoped().bulk_create(
            [_health_row(self.team.id, YESTERDAY - dt.timedelta(days=offset)) for offset in range(40)]
            + [_health_row(other_team_id, YESTERDAY)]
        )

        assert delete_days_before(EventsHealthDailyRollup, YESTERDAY - dt.timedelta(days=34)) == 5
        assert EventsHealthDaily.objects.for_team(self.team.id).count() == 35

        assert delete_rollup_rows_for_teams(EventsHealthDaily, [self.team.id]) == 35
        assert EventsHealthDaily.objects.unscoped().count() == 1

    def test_check_skips_the_batch_and_keeps_issues_when_the_rollup_is_stale(self) -> None:
        issue = HealthIssue.objects.create(
            team=self.team,
            kind=STUB_KIND,
            severity=HealthIssue.Severity.WARNING,
            payload={},
            unique_hash=HealthIssue.compute_unique_hash(STUB_KIND, {}, []),
        )
        EventsHealthDaily.objects.unscoped().bulk_create(
            [_health_row(self.team.id, YESTERDAY - dt.timedelta(days=offset)) for offset in range(2, 40)]
        )

        result = _process_batch_detection([self.team.id], STUB_KIND, _StubRollupCheck().detect, dry_run=False)

        assert result.teams_skipped == 1
        issue.refresh_from_db()
        assert issue.status == HealthIssue.Status.ACTIVE
