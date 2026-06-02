from datetime import datetime
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.api.annotation_context import resolve_snapshot_date_range
from posthog.models import Annotation
from posthog.temporal.subscriptions.snapshot_activities import _load_annotations_section

from products.product_analytics.backend.models.insight import Insight


def _snap_with_range(date_from: str | None, date_to: str | None) -> dict:
    qr: dict = {}
    if date_from is not None and date_to is not None:
        qr["resolved_date_range"] = {"date_from": date_from, "date_to": date_to}
    return {"insights": [{"id": 1, "query_results": qr}]}


class TestResolveSnapshotDateRange:
    @parameterized.expand(
        [
            ("no_snapshots", [], False),
            ("snapshot_without_insights", [{"insights": []}], False),
            ("missing_resolved_date_range", [_snap_with_range(None, None)], False),
            (
                "malformed_dates",
                [
                    {
                        "insights": [
                            {
                                "id": 1,
                                "query_results": {
                                    "resolved_date_range": {"date_from": "garbage", "date_to": "also-garbage"}
                                },
                            }
                        ]
                    }
                ],
                False,
            ),
            (
                "single_valid_range",
                [_snap_with_range("2025-04-01T00:00:00Z", "2025-04-15T00:00:00Z")],
                True,
            ),
        ]
    )
    def test_resolve_snapshot_date_range(self, _name: str, snapshots: list[dict], expect_window: bool) -> None:
        result = resolve_snapshot_date_range(snapshots)
        assert (result is not None) is expect_window

    def test_combines_ranges_across_snapshots(self) -> None:
        snapshots = [
            _snap_with_range("2025-04-01T00:00:00Z", "2025-04-07T00:00:00Z"),
            _snap_with_range("2025-04-10T00:00:00Z", "2025-04-20T00:00:00Z"),
        ]
        result = resolve_snapshot_date_range(snapshots)
        assert result is not None
        date_from, date_to = result
        assert date_from == datetime(2025, 4, 1, tzinfo=ZoneInfo("UTC"))
        assert date_to == datetime(2025, 4, 20, tzinfo=ZoneInfo("UTC"))


@pytest.mark.django_db
class TestLoadAnnotationsSection(APIBaseTest):
    def _subscription_like(self, dashboard_id: int | None = None) -> Any:
        return SimpleNamespace(team=self.team, dashboard_id=dashboard_id)

    def test_returns_empty_string_when_no_date_window(self) -> None:
        result = _load_annotations_section(self._subscription_like(), [], [])
        assert result == ""

    def test_returns_empty_string_when_window_present_but_no_annotations(self) -> None:
        snapshots = [_snap_with_range("2025-04-01T00:00:00Z", "2025-04-15T00:00:00Z")]
        result = _load_annotations_section(self._subscription_like(), snapshots, [])
        assert result == ""

    def test_renders_annotations_for_insight_in_window(self) -> None:
        insight = Insight.objects.create(team=self.team, name="Pageviews")
        Annotation.objects.create(
            organization=self.organization,
            team=self.team,
            content="rolled out new home page flag",
            date_marker=datetime(2025, 4, 5, tzinfo=ZoneInfo("UTC")),
            scope=Annotation.Scope.INSIGHT,
            dashboard_item=insight,
        )
        snapshots = [_snap_with_range("2025-04-01T00:00:00Z", "2025-04-15T00:00:00Z")]

        result = _load_annotations_section(self._subscription_like(), snapshots, [insight.id])

        assert "rolled out new home page flag" in result
        assert "Annotations during this period" in result
