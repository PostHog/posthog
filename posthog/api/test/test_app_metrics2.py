from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from posthog.api.app_metrics2 import AppMetricsMixin, AppMetricsRequestSerializer, MetricSeries, fetch_app_metric_totals
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


class _PlainViewSet(AppMetricsMixin):
    app_source = "hog_function"


class _VersionedRequestSerializer(AppMetricsRequestSerializer):
    version = serializers.IntegerField(required=False)


class _VersionedViewSet(AppMetricsMixin):
    app_source = "hog_flow_ish"
    metrics_request_serializer_class = _VersionedRequestSerializer


class TestAppMetricsMixinSeries(SimpleTestCase):
    def _request(self, **params: str) -> Request:
        return Request(APIRequestFactory().get("/", params))  # ty: ignore[invalid-return-type]

    @parameterized.expand(
        [
            ("declared", _VersionedViewSet, True),
            ("undeclared", _PlainViewSet, False),
        ]
    )
    def test_a_narrowing_parameter_is_refused_unless_the_endpoint_declares_it(
        self, _name: str, viewset_class: type[AppMetricsMixin], accepted: bool
    ) -> None:
        if accepted:
            assert viewset_class()._metrics_params(self._request(version="2")).is_valid()
            return
        with pytest.raises(serializers.ValidationError) as err:
            viewset_class()._metrics_params(self._request(version="2"))
        assert "version" in err.value.detail

    def test_an_undeclared_parameter_that_narrows_nothing_is_still_ignored(self) -> None:
        assert _PlainViewSet()._metrics_params(self._request(nonsense="1")).is_valid()

    def test_the_default_series_is_the_object_s_own_whole_history(self) -> None:
        series = _PlainViewSet()._metric_series_for(SimpleNamespace(id="fn-1"), {"version": 2})
        assert series == MetricSeries(app_source="hog_function", app_source_id="fn-1")
