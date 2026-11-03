import datetime as dt

import pytest
import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events, materialized
from unittest.mock import patch

from django.core.cache import cache

import dagster
from parameterized import parameterized

from posthog.dags.daily_rollups import DailyRollupConfig
from posthog.models.health_issue import HealthIssue
from posthog.models.team import Team
from posthog.temporal.health_checks.models import HealthCheckResult
from posthog.temporal.health_checks.processing import _process_batch_detection
from posthog.temporal.health_checks.rollups import checks, store
from posthog.temporal.health_checks.rollups.checks import RollupHealthCheck
from posthog.temporal.health_checks.rollups.freshness import RollupWindow
from posthog.temporal.health_checks.rollups.runner import RollupDay, RollupDayRefused, run_rollup_day
from posthog.temporal.health_checks.rollups.store import delete_days_before, delete_rollup_rows_for_teams

from products.growth.backend.models import SdkVersionsDaily
from products.growth.backend.sdk_version_rollup import SdkVersionsDailyRollup
from products.growth.backend.temporal.health_checks.sdk_outdated import SdkOutdatedCheck
from products.growth.dags.sdk_versions_rollup import sdk_versions_daily_rollup
from products.web_analytics.backend.models.health_rollups import EventsHealthDaily, HostProxyDaily, SessionIdState
from products.web_analytics.backend.rollups import host_proxy
from products.web_analytics.backend.rollups.host_proxy import HostProxyDailyRollup

YESTERDAY = dt.date(2026, 10, 28)
NOON_YESTERDAY = dt.datetime.combine(YESTERDAY, dt.time(12), tzinfo=dt.UTC)
EVENT_ISSUE = HealthCheckResult(severity=HealthIssue.Severity.WARNING, payload={"source": "events"})


class _ShadowRollupCheck(RollupHealthCheck):
    kind = "rollup_shadow_stub"
    rollup_model = EventsHealthDaily
    window_days = 7
    reads_rollup = False

    def detect_from_events(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        return {team_id: [EVENT_ISSUE] for team_id in team_ids}

    def detect_from_rollup(self, team_ids: list[int], window: RollupWindow) -> dict[int, list[HealthCheckResult]]:
        return {}


def _sdk_row(team_id: int, day: dt.date, event_count: int = 1) -> SdkVersionsDaily:
    return SdkVersionsDaily(
        team_id=team_id,
        day=day,
        lib="web",
        lib_version="1.0.0",
        event_count=event_count,
        max_timestamp=dt.datetime.combine(day, dt.time(12), tzinfo=dt.UTC),
    )


@time_machine.travel("2026-10-29T12:00:00Z", tick=False)
class TestRollupFillAndPublish(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    def _capture_sdk_events(self, team: Team, events: list[tuple[str, str]], timestamp: dt.datetime) -> None:
        for lib, version in events:
            _create_event(
                team=team,
                event="$pageview",
                distinct_id="user",
                timestamp=timestamp,
                properties={"$lib": lib, "$lib_version": version},
            )

    def test_publish_replaces_one_day_and_drops_deleted_teams(self) -> None:
        deleted_team = Team.objects.create(organization=self.organization)
        with materialized("events", "$lib"), materialized("events", "$lib_version"):
            self._capture_sdk_events(self.team, [("web", "1.0.0")] * 3, NOON_YESTERDAY)
            self._capture_sdk_events(deleted_team, [("web", "1.0.0")], NOON_YESTERDAY)
            flush_persons_and_events()
            Team.objects.filter(pk=deleted_team.pk).delete()
            other_day = _sdk_row(self.team.id, YESTERDAY - dt.timedelta(days=5), event_count=7)
            SdkVersionsDaily.objects.unscoped().bulk_create([other_day])

            run_rollup_day(SdkVersionsDailyRollup, RollupDay(day=YESTERDAY, mode="publish"))
            run_rollup_day(SdkVersionsDailyRollup, RollupDay(day=YESTERDAY, mode="publish"))

        rows = list(SdkVersionsDaily.objects.unscoped().values_list("team_id", "day", "event_count").order_by("day"))
        assert rows == [(self.team.id, other_day.day, 7), (self.team.id, YESTERDAY, 3)]

    def test_refused_day_keeps_the_published_rows(self) -> None:
        SdkVersionsDaily.objects.unscoped().bulk_create([_sdk_row(self.team.id, YESTERDAY, event_count=9)])

        with materialized("events", "$lib"), materialized("events", "$lib_version"):
            with pytest.raises(RollupDayRefused, match="no rows"):
                run_rollup_day(SdkVersionsDailyRollup, RollupDay(day=YESTERDAY, mode="publish"))

        assert list(SdkVersionsDaily.objects.for_team(self.team.id).values_list("event_count", flat=True)) == [9]

    def test_day_over_the_row_cap_is_refused_even_when_forced(self) -> None:
        with materialized("events", "$lib"), materialized("events", "$lib_version"):
            self._capture_sdk_events(self.team, [("web", "1.0.0"), ("web", "1.1.0"), ("web", "1.2.0")], NOON_YESTERDAY)
            flush_persons_and_events()

            with (
                patch.object(SdkVersionsDailyRollup, "max_rows_per_day", 1),
                pytest.raises(RollupDayRefused, match="more than 1 rows"),
            ):
                run_rollup_day(SdkVersionsDailyRollup, RollupDay(day=YESTERDAY, mode="publish"), force=True)

        assert not SdkVersionsDaily.objects.for_team(self.team.id).exists()

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
            self._capture_sdk_events(self.team, events, NOON_YESTERDAY)
            flush_persons_and_events()

            run_rollup_day(SdkVersionsDailyRollup, RollupDay(day=YESTERDAY, mode="publish"))

        rows = set(SdkVersionsDaily.objects.for_team(self.team.id).values_list("lib", "lib_version", "event_count"))
        assert rows == {("web", "1.200.0", 2), ("posthog-java", "", 1), ("posthog-node", "4.0.0-beta.1", 1)}

    @patch.object(host_proxy, "MAX_HOSTS_PER_TEAM_DAY", 1)
    def test_host_fill_keeps_the_proxied_row_of_a_busy_unproxied_host(self) -> None:
        traffic = [("www.example.com", False)] * 3 + [("www.example.com", True)] + [("app.example.com", True)] * 2
        with materialized("events", "$host"), materialized("events", "$lib_custom_api_host"):
            for host, proxied in traffic:
                properties = {"$host": host, **({"$lib_custom_api_host": "https://e.example.com"} if proxied else {})}
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id="user",
                    timestamp=NOON_YESTERDAY,
                    properties=properties,
                )
            flush_persons_and_events()

            run_rollup_day(HostProxyDailyRollup, RollupDay(day=YESTERDAY, mode="publish"))

        rows = set(
            HostProxyDaily.objects.for_team(self.team.id).values_list("host", "has_custom_api_host", "event_count")
        )
        assert rows == {("www.example.com", False, 3), ("www.example.com", True, 1)}

    @patch.object(store, "DELETE_BATCH_SIZE", 2)
    def test_batched_deletes_remove_every_matching_row(self) -> None:
        other_team_id = self.team.id + 1
        SdkVersionsDaily.objects.unscoped().bulk_create(
            [_sdk_row(self.team.id, YESTERDAY - dt.timedelta(days=offset)) for offset in range(15)]
            + [_sdk_row(other_team_id, YESTERDAY)]
        )

        assert delete_days_before(SdkVersionsDailyRollup, YESTERDAY - dt.timedelta(days=9)) == 5
        assert SdkVersionsDaily.objects.for_team(self.team.id).count() == 10

        assert delete_rollup_rows_for_teams(SdkVersionsDaily, [self.team.id]) == 10
        assert SdkVersionsDaily.objects.unscoped().count() == 1

    def test_scheduled_job_publishes_the_good_days_and_cleans_up_before_failing_on_a_refused_day(self) -> None:
        expired_day = YESTERDAY - dt.timedelta(days=20)
        deleted_team_id = self.team.id + 1000
        SdkVersionsDaily.objects.unscoped().bulk_create(
            [_sdk_row(self.team.id, expired_day), _sdk_row(deleted_team_id, YESTERDAY - dt.timedelta(days=4))]
        )
        with materialized("events", "$lib"), materialized("events", "$lib_version"):
            self._capture_sdk_events(self.team, [("web", "1.0.0")], NOON_YESTERDAY)
            self._capture_sdk_events(self.team, [("web", "1.0.0")] * 2, NOON_YESTERDAY - dt.timedelta(days=3))
            flush_persons_and_events()

            result = sdk_versions_daily_rollup.job.execute_in_process(raise_on_error=False)

        assert not result.success
        failure = result.failure_data_for_node(f"fill_{SdkVersionsDailyRollup.table()}")
        assert failure is not None and "Launch the job with `days`" in str(failure.error)

        published = set(SdkVersionsDaily.objects.unscoped().values_list("team_id", "day", "event_count"))
        assert published == {(self.team.id, YESTERDAY, 1), (self.team.id, YESTERDAY - dt.timedelta(days=3), 2)}

    def test_requested_day_with_force_publishes_under_the_median(self) -> None:
        SdkVersionsDaily.objects.unscoped().bulk_create(
            [
                _sdk_row(team_id, YESTERDAY - dt.timedelta(days=offset))
                for offset in range(2, 6)
                for team_id in range(self.team.id, self.team.id + 10)
            ]
        )
        with materialized("events", "$lib"), materialized("events", "$lib_version"):
            self._capture_sdk_events(self.team, [("web", "1.0.0")], NOON_YESTERDAY)
            flush_persons_and_events()
            op = f"fill_{SdkVersionsDailyRollup.table()}"
            requested = DailyRollupConfig(days=[YESTERDAY.isoformat()])

            refused = sdk_versions_daily_rollup.job.execute_in_process(
                run_config=dagster.RunConfig(ops={op: requested}), raise_on_error=False
            )
            forced = sdk_versions_daily_rollup.job.execute_in_process(
                run_config=dagster.RunConfig(ops={op: DailyRollupConfig(days=requested.days, force=True)})
            )

        assert not refused.success
        assert forced.success
        assert list(
            SdkVersionsDaily.objects.for_team(self.team.id).filter(day=YESTERDAY).values_list("event_count", flat=True)
        ) == [1]

    def test_check_skips_the_batch_and_keeps_issues_when_the_rollup_is_stale(self) -> None:
        issue = HealthIssue.objects.create(
            team=self.team,
            kind=SdkOutdatedCheck.kind,
            severity=HealthIssue.Severity.WARNING,
            payload={"sdk_name": "web"},
            unique_hash=HealthIssue.compute_unique_hash(SdkOutdatedCheck.kind, {"sdk_name": "web"}, ["sdk_name"]),
        )
        SdkVersionsDaily.objects.unscoped().bulk_create(
            [_sdk_row(self.team.id, YESTERDAY - dt.timedelta(days=offset)) for offset in range(2, 10)]
        )

        result = _process_batch_detection([self.team.id], SdkOutdatedCheck.kind, SdkOutdatedCheck().detect)

        assert result.teams_skipped == 1
        issue.refresh_from_db()
        assert issue.status == HealthIssue.Status.ACTIVE

    @parameterized.expand([("fresh_rollup", 1), ("stale_rollup", 5)])
    @patch.object(checks, "COMPARISON_SAMPLE_RATE", 1.0)
    def test_check_not_reading_the_rollup_serves_event_issues(self, _name: str, newest_day_offset: int) -> None:
        EventsHealthDaily.objects.unscoped().bulk_create(
            [
                EventsHealthDaily(
                    team_id=self.team.id,
                    day=YESTERDAY - dt.timedelta(days=offset - 1),
                    event="$pageview",
                    has_custom_api_host=False,
                    has_scroll_depth=False,
                    session_id_state=SessionIdState.VALID,
                    event_count=1,
                )
                for offset in range(newest_day_offset, newest_day_offset + 7)
            ]
        )

        assert _ShadowRollupCheck().detect([self.team.id]) == {self.team.id: [EVENT_ISSUE]}

    @patch.object(checks, "rollup_window", side_effect=RuntimeError("cache unavailable"))
    def test_check_not_reading_the_rollup_serves_event_issues_when_the_freshness_lookup_fails(
        self, _rollup_window: object
    ) -> None:
        assert _ShadowRollupCheck().detect([self.team.id]) == {self.team.id: [EVENT_ISSUE]}
