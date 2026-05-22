from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.api.annotation_context import (
    format_annotations_for_prompt,
    get_annotations_for_ai_context,
    resolve_dashboard_date_range,
    resolve_query_date_range,
)
from posthog.models import Annotation, Insight, Organization, Team

from products.dashboards.backend.models.dashboard import Dashboard


class TestAnnotationContext(APIBaseTest):
    def _make_annotation(
        self,
        content: str,
        date_marker: datetime,
        scope: str = Annotation.Scope.PROJECT,
        dashboard: Dashboard | None = None,
        dashboard_item: Insight | None = None,
        team: Team | None = None,
        organization: Organization | None = None,
        deleted: bool = False,
    ) -> Annotation:
        return Annotation.objects.create(
            organization=organization or self.organization,
            team=team or self.team,
            content=content,
            date_marker=date_marker,
            scope=scope,
            dashboard=dashboard,
            dashboard_item=dashboard_item,
            deleted=deleted,
        )

    def test_returns_project_and_organization_scoped_annotations_in_window(self) -> None:
        in_window = datetime(2026, 1, 5, tzinfo=ZoneInfo("UTC"))
        out_of_window = datetime(2025, 11, 1, tzinfo=ZoneInfo("UTC"))
        self._make_annotation("rolled out new home page", in_window)
        self._make_annotation("org-wide release", in_window, scope=Annotation.Scope.ORGANIZATION)
        self._make_annotation("ancient", out_of_window)

        result = get_annotations_for_ai_context(
            self.team,
            datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")),
            datetime(2026, 1, 31, tzinfo=ZoneInfo("UTC")),
        )

        contents = sorted(a["content"] for a in result)
        assert contents == ["org-wide release", "rolled out new home page"]

    def test_excludes_other_dashboard_and_insight_scoped_annotations(self) -> None:
        in_window = datetime(2026, 1, 5, tzinfo=ZoneInfo("UTC"))
        my_dashboard = Dashboard.objects.create(team=self.team, name="mine")
        other_dashboard = Dashboard.objects.create(team=self.team, name="other")
        my_insight = Insight.objects.create(team=self.team, name="mine")
        other_insight = Insight.objects.create(team=self.team, name="other")

        self._make_annotation("on my dashboard", in_window, scope=Annotation.Scope.DASHBOARD, dashboard=my_dashboard)
        self._make_annotation(
            "on other dashboard", in_window, scope=Annotation.Scope.DASHBOARD, dashboard=other_dashboard
        )
        self._make_annotation("on my insight", in_window, scope=Annotation.Scope.INSIGHT, dashboard_item=my_insight)
        self._make_annotation(
            "on other insight", in_window, scope=Annotation.Scope.INSIGHT, dashboard_item=other_insight
        )

        result = get_annotations_for_ai_context(
            self.team,
            datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")),
            datetime(2026, 1, 31, tzinfo=ZoneInfo("UTC")),
            dashboard_id=my_dashboard.id,
            insight_id=my_insight.id,
        )

        contents = sorted(a["content"] for a in result)
        assert contents == ["on my dashboard", "on my insight"]

    def test_excludes_deleted_and_other_team_annotations(self) -> None:
        in_window = datetime(2026, 1, 5, tzinfo=ZoneInfo("UTC"))
        other_team = Team.objects.create(organization=Organization.objects.create(name="other"), name="other")
        self._make_annotation("deleted", in_window, deleted=True)
        self._make_annotation("other team", in_window, team=other_team, organization=other_team.organization)
        self._make_annotation("kept", in_window)

        result = get_annotations_for_ai_context(
            self.team,
            datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")),
            datetime(2026, 1, 31, tzinfo=ZoneInfo("UTC")),
        )

        assert [a["content"] for a in result] == ["kept"]

    @parameterized.expand(
        [
            ("absolute_iso", "2026-01-01T00:00:00Z", "2026-01-31T00:00:00Z", True),
            ("relative_from_only", "-7d", None, True),
            ("missing_from", None, "2026-01-31T00:00:00Z", False),
            ("empty_strings", "", "", False),
            ("garbage", "not-a-date", None, False),
        ]
    )
    def test_resolve_dashboard_date_range(
        self, _name: str, raw_from: str | None, raw_to: str | None, expected_some: bool
    ) -> None:
        filters = {"date_from": raw_from, "date_to": raw_to}
        result = resolve_dashboard_date_range(filters, self.team)
        assert (result is not None) is expected_some

    def test_resolve_query_date_range_handles_missing_pieces(self) -> None:
        class _DR:
            date_from = "-30d"
            date_to = None

        class _Source:
            dateRange = _DR()

        class _Query:
            source = _Source()

        result = resolve_query_date_range(_Query(), self.team)
        assert result is not None
        date_from, date_to = result
        assert date_to - date_from >= timedelta(days=29)

    def test_resolve_query_date_range_returns_none_without_date_range(self) -> None:
        class _Source:
            dateRange = None

        class _Query:
            source = _Source()

        assert resolve_query_date_range(_Query(), self.team) is None

    def test_format_annotations_for_prompt_empty(self) -> None:
        assert format_annotations_for_prompt([]) == ""
        assert format_annotations_for_prompt([{"content": None, "date_marker": None, "scope": "project"}]) == ""

    def test_format_annotations_for_prompt_renders_lines(self) -> None:
        block = format_annotations_for_prompt(
            [
                {
                    "date_marker": datetime(2026, 1, 5, 10, tzinfo=ZoneInfo("UTC")),
                    "content": "rolled out new home page flag",
                    "scope": "project",
                }
            ]
        )
        assert "rolled out new home page flag" in block
        assert "2026-01-05" in block
        assert "project" in block
