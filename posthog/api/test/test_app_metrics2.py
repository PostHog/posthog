from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from posthog.test.base import BaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.api.app_metrics2 import fetch_app_metric_totals, fetch_app_metric_totals_by_source
from posthog.test.fixtures import create_app_metric2


class TestAppMetrics2Timezone(ClickhouseTestMixin, BaseTest):
    def _seed(self, when_utc: datetime, app_source_id: str = "fn-1") -> None:
        create_app_metric2(
            team_id=self.team.pk,
            app_source="hog_function",
            app_source_id=app_source_id,
            metric_kind="success",
            metric_name="succeeded",
            timestamp=when_utc,
        )

    @parameterized.expand(
        [
            ("instance_id", {"instance_id": "54321"}),  # the fixture's default instance
            ("name", {"name": ["succeeded"]}),
            ("kind", {"kind": ["success"]}),
        ]
    )
    def test_totals_optional_filters_are_bound(self, _name: str, filters: dict[str, Any]) -> None:
        self._seed(datetime(2026, 6, 8, 12, 0, 0, tzinfo=UTC), app_source_id="fn-filters")

        result = fetch_app_metric_totals(
            team_id=self.team.pk, app_source="hog_function", app_source_id="fn-filters", **filters
        )

        assert result.totals == {"success": 1}

    @parameterized.expand(
        [
            ("America/Los_Angeles",),  # -07:00 (PDT in June)
            ("Asia/Kolkata",),  # +05:30 (half-hour offset)
            ("Pacific/Auckland",),  # +12:00 (wraps to the previous UTC day)
        ]
    )
    def test_totals_window_bound_is_utc_not_team_local(self, tz_name: str):
        tz = ZoneInfo(tz_name)
        after_local = datetime(2026, 6, 8, 0, 0, 0, tzinfo=tz)
        before_local = datetime(2026, 6, 9, 0, 0, 0, tzinfo=tz)
        bound_utc = after_local.astimezone(UTC)
        self._seed(bound_utc - timedelta(hours=1))  # an hour before the true bound — excluded
        self._seed(bound_utc + timedelta(hours=1))  # an hour after — included

        result = fetch_app_metric_totals(
            team_id=self.team.pk,
            app_source="hog_function",
            app_source_id="fn-1",
            after=after_local,
            before=before_local,
        )

        # Local-midnight `after` must resolve to its true UTC instant. A naive bound (the offset
        # dropped, read as UTC) would shift the window and miscount the row near the boundary —
        # for negative offsets it pulls in the earlier row, for positive ones it drops both.
        # `fetch_app_metrics_trends` shares the identical conversion, so this guards it too.
        assert result.totals == {"success": 1}, tz_name


class TestAppMetrics2BySource(ClickhouseTestMixin, BaseTest):
    def _seed(self, app_source_id: str, instance_id: str = "step-1", metric_name: str = "succeeded") -> None:
        create_app_metric2(
            team_id=self.team.pk,
            app_source="hog_flow_version",
            app_source_id=app_source_id,
            instance_id=instance_id,
            metric_kind="success",
            metric_name=metric_name,
            timestamp=datetime(2026, 6, 8, 12, 0, 0, tzinfo=UTC),
        )

    def _read(self, **kwargs) -> dict[str, dict[str, int]]:
        return fetch_app_metric_totals_by_source(
            team_id=self.team.pk, app_source="hog_flow_version", name=["succeeded"], **kwargs
        )

    def test_it_groups_every_source_when_no_ids_are_named(self) -> None:
        self._seed("flow-a/1")
        self._seed("flow-b/1")

        assert set(self._read()) == {"flow-a/1", "flow-b/1"}

    def test_named_ids_leave_the_other_sources_out(self) -> None:
        self._seed("flow-a/1")
        self._seed("flow-a/2")
        self._seed("flow-b/1")

        assert set(self._read(app_source_ids=["flow-a/1", "flow-a/2"])) == {"flow-a/1", "flow-a/2"}

    def test_an_empty_id_list_reads_nothing_rather_than_everything(self) -> None:
        self._seed("flow-a/1")
        self._seed("flow-b/1")

        # Falling through to the unfiltered query would hand the caller every workflow's counts.
        assert self._read(app_source_ids=[]) == {}

    def test_an_instance_id_leaves_the_other_steps_out(self) -> None:
        self._seed("flow-a/1", instance_id="step-1")
        self._seed("flow-a/1", instance_id="step-2")

        assert self._read(app_source_ids=["flow-a/1"], instance_id="step-1") == {"flow-a/1": {"succeeded": 1}}
        assert self._read(app_source_ids=["flow-a/1"]) == {"flow-a/1": {"succeeded": 2}}
