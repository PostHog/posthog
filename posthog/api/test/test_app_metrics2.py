from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from posthog.test.base import APIBaseTest, BaseTest, ClickhouseTestMixin

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.api.app_metrics2 import (
    MAX_TREND_BUCKETS,
    MAX_ZERO_FILLED_CELLS,
    AppMetricsRequestSerializer,
    fetch_app_metric_totals,
    fetch_app_metrics_trends,
)
from posthog.test.fixtures import create_app_metric2

from products.cdp.backend.models.hog_functions.hog_function import HogFunction

DISTINCT_51 = ",".join(f"metric_{i}" for i in range(51))


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
            ("name", {"name": ["succeeded", "skipped"]}, "skipped"),
            ("kind", {"kind": ["success", "failure"]}, "failure"),
        ]
    )
    def test_requested_breakdown_values_without_rows_read_as_zero(
        self, breakdown_by: str, filters: dict[str, Any], missing: str
    ) -> None:
        after = datetime(2026, 6, 8, 0, 0, tzinfo=UTC)
        before = datetime(2026, 6, 9, 23, 0, tzinfo=UTC)
        self._seed(after + timedelta(hours=12))
        query = {
            "team_id": self.team.pk,
            "app_source": "hog_function",
            "app_source_id": "fn-1",
            "after": after,
            "before": before,
            "breakdown_by": breakdown_by,
            **filters,
        }

        trends = fetch_app_metrics_trends(**query)
        totals = fetch_app_metric_totals(**query)

        assert {series.name: series.values for series in trends.series}[missing] == [0, 0]
        assert totals.totals[missing] == 0

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

    @parameterized.expand(
        [
            ("day", datetime(2026, 6, 8, 12, 0, tzinfo=UTC), datetime(2026, 6, 8, 13, 0, 0, 500000, tzinfo=UTC), [2]),
            (
                "hour",
                datetime(2026, 6, 8, 9, 30, tzinfo=UTC),
                datetime(2026, 6, 8, 11, 30, 0, 500000, tzinfo=UTC),
                [1, 0, 1],
            ),
        ]
    )
    def test_trends_and_totals_count_rows_at_the_range_edges(
        self, interval: str, after: datetime, before: datetime, expected: list[int]
    ) -> None:
        # The rows sit in different clock hours because the table can merge rows of one hour into one row.
        self._seed(after - timedelta(hours=1))  # before `after`: excluded
        self._seed(after + timedelta(minutes=15))  # in range, in a bucket that starts before `after`: included
        self._seed(before - timedelta(microseconds=250000))  # in the same second as `before`, but earlier: included

        trends = fetch_app_metrics_trends(
            team_id=self.team.pk,
            app_source="hog_function",
            app_source_id="fn-1",
            after=after,
            before=before,
            interval=interval,
        )
        totals = fetch_app_metric_totals(
            team_id=self.team.pk, app_source="hog_function", app_source_id="fn-1", after=after, before=before
        )

        assert [(series.name, series.values) for series in trends.series] == [("success", expected)]
        assert totals.totals == {"success": sum(expected)}


class TestAppMetricsRequestSerializer(SimpleTestCase):
    @parameterized.expand(
        [
            ("name_at_limit", "name", ",".join(f"m{i}" for i in range(50)), [f"m{i}" for i in range(50)]),
            ("kind_duplicates_and_blanks", "kind", " success, failure,,success ," * 40, ["success", "failure"]),
            ("name_over_limit", "name", DISTINCT_51, None),
            ("kind_over_limit", "kind", DISTINCT_51, None),
            ("name_only_blanks", "name", ", ,,", None),
        ]
    )
    def test_requested_values_are_deduped_and_capped(
        self, _name: str, field: str, raw: str, expected: list[str] | None
    ) -> None:
        serializer = AppMetricsRequestSerializer(data={field: raw})

        if expected is None:
            assert not serializer.is_valid()
            assert field in serializer.errors
        else:
            assert serializer.is_valid(), serializer.errors
            assert serializer.validated_data[field] == expected


class TestAppMetricsEndpointLimits(APIBaseTest):
    @parameterized.expand([("metrics/",), ("metrics/totals/",)])
    def test_too_many_requested_names_is_a_400(self, path: str) -> None:
        hog_function = HogFunction.objects.create(team=self.team, name="destination", type="destination", hog="")

        response = self.client.get(
            f"/api/projects/{self.team.id}/hog_functions/{hog_function.id}/{path}",
            {"name": DISTINCT_51, "breakdown_by": "name", "interval": "hour"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["attr"] == "name"

    @parameterized.expand(
        [
            ("buckets_at_limit", 0, MAX_TREND_BUCKETS, None),
            ("buckets_over_limit", 0, MAX_TREND_BUCKETS + 1, "Use a shorter range or a larger interval."),
            ("cells_at_limit", 50, MAX_ZERO_FILLED_CELLS // 50, None),
            ("cells_over_limit", 50, MAX_ZERO_FILLED_CELLS // 50 + 1, "Request fewer names or kinds"),
        ]
    )
    def test_trend_size_is_capped(self, _name: str, name_count: int, bucket_count: int, error: str | None) -> None:
        hog_function = HogFunction.objects.create(team=self.team, name="destination", type="destination", hog="")
        after = datetime(2020, 1, 1, tzinfo=UTC)
        params = {
            "after": after.isoformat(),
            "before": (after + timedelta(hours=bucket_count - 1)).isoformat(),
            "interval": "hour",
        }
        if name_count:
            params |= {"name": ",".join(f"m{i}" for i in range(name_count)), "breakdown_by": "name"}

        response = self.client.get(f"/api/projects/{self.team.id}/hog_functions/{hog_function.id}/metrics/", params)

        if error is None:
            assert response.status_code == status.HTTP_200_OK, response.json()
            assert len(response.json()["labels"]) == bucket_count
            assert len(response.json()["series"]) == name_count
        else:
            assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
            assert error in response.json()["detail"]
