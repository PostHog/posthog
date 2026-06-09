from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.api.app_metrics2 import fetch_app_metric_totals
from posthog.test.fixtures import create_app_metric2

# America/Los_Angeles is UTC-7 in June (PDT), so PT midnight is 07:00 UTC.
LA = ZoneInfo("America/Los_Angeles")


class TestAppMetrics2Timezone(ClickhouseTestMixin, BaseTest):
    def _seed(self, hour_utc: int):
        create_app_metric2(
            team_id=self.team.pk,
            app_source="hog_function",
            app_source_id="fn-1",
            metric_kind="success",
            metric_name="succeeded",
            timestamp=datetime(2026, 6, 8, hour_utc, 0, 0, tzinfo=UTC),
        )

    def test_totals_window_bound_is_utc_not_team_local(self):
        self._seed(6)  # 06:00 UTC — before the 07:00 UTC bound
        self._seed(8)  # 08:00 UTC — after it
        result = fetch_app_metric_totals(
            team_id=self.team.pk,
            app_source="hog_function",
            app_source_id="fn-1",
            after=datetime(2026, 6, 8, 0, 0, 0, tzinfo=LA),
            before=datetime(2026, 6, 9, 0, 0, 0, tzinfo=LA),
        )
        # Only the 08:00 UTC row is inside the PT-midnight window; a naive bound read as 00:00 UTC
        # would have counted both. `fetch_app_metrics_trends` shares the identical UTC conversion,
        # so this also guards that path (and day-grain trends can't isolate the offset anyway).
        assert result.totals == {"success": 1}
