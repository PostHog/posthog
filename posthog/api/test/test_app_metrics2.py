from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from posthog.test.base import BaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.api.app_metrics2 import fetch_app_metric_totals
from posthog.test.fixtures import create_app_metric2


class TestAppMetrics2Timezone(ClickhouseTestMixin, BaseTest):
    def _seed(self, when_utc: datetime, app_source_id: str = "fn-1"):
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
    def test_totals_optional_filters_are_bound(self, _name: str, filters: dict):
        # Each of these renders a placeholder into the SQL, so an unbound one raises KeyError before
        # the query runs — a 500 on `/metrics/totals?name=…` for every hog function and hog flow.
        # Its own app_source_id: ClickHouse rows outlive a test, so sharing one would land these rows
        # inside the window the timezone cases below count.
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
