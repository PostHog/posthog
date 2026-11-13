from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest

from django.utils import timezone

from parameterized import parameterized

from posthog.models import Organization, Team

from products.annotations.backend.facade import api
from products.annotations.backend.facade.contracts import AnnotationWrite, AnnotationWriteRejectedError
from products.annotations.backend.facade.enums import AnnotationScope
from products.annotations.backend.models.annotation import Annotation
from products.dashboards.backend.models.dashboard import Dashboard
from products.product_analytics.backend.facade.models import Insight


class TestListDatedAnnotations(BaseTest):
    def _annotation(self, days_ago: float = 1, **kwargs: Any) -> Annotation:
        fields: dict[str, Any] = {
            "team": self.team,
            "organization": self.organization,
            "content": "Shipped v2.3",
            "scope": AnnotationScope.PROJECT,
            "date_marker": timezone.now() - timedelta(days=days_ago),
            **kwargs,
        }
        return Annotation.objects.create(**fields)

    def _list(self, limit: int = 10) -> list[str]:
        now = timezone.now()
        dated = api.list_dated_annotations(
            team_id=self.team.id,
            organization_id=self.organization.id,
            start=now - timedelta(days=7),
            end=now,
            limit=limit,
        )
        return [annotation.content for annotation in dated]

    @parameterized.expand(
        [
            ("in_window", {}, ["Shipped v2.3"]),
            ("insight_scope_counts", {"scope": AnnotationScope.INSIGHT}, ["Shipped v2.3"]),
            ("before_window", {"days_ago": 8}, []),
            ("future_dated", {"days_ago": -1}, []),
            ("deleted", {"deleted": True}, []),
            ("no_content", {"content": None}, []),
            ("empty_content", {"content": ""}, []),
            ("no_marker_falls_back_to_creation_time", {"date_marker": None}, ["Shipped v2.3"]),
        ]
    )
    def test_window_and_content_rules(self, _name: str, overrides: dict[str, Any], expected: list[str]) -> None:
        self._annotation(**overrides)

        assert self._list() == expected

    def test_sees_org_scoped_annotations_of_sibling_teams_only(self) -> None:
        sibling_team = Team.objects.create(organization=self.organization, name="Sibling")
        self._annotation(team=sibling_team, scope=AnnotationScope.ORGANIZATION, content="Org-wide incident")
        self._annotation(team=sibling_team, content="Sibling project note")
        other_org = Organization.objects.create(name="Other")
        other_team = Team.objects.create(organization=other_org, name="Other team")
        self._annotation(team=other_team, organization=other_org, scope=AnnotationScope.ORGANIZATION)

        assert self._list() == ["Org-wide incident"]

    def test_limit_keeps_the_newest(self) -> None:
        for hours_ago in range(4):
            self._annotation(days_ago=hours_ago / 24, content=f"annotation {hours_ago}")

        assert self._list(limit=2) == ["annotation 0", "annotation 1"]


class TestAnnotationWrites(BaseTest):
    def test_project_annotation_defaults_its_marker_to_now(self) -> None:
        annotation_id = api.create_project_annotation(self.team.id, self.user.id, content="Marked from the canvas")

        annotation = api.get_annotation(
            team_id=self.team.id, organization_id=self.organization.id, annotation_id=annotation_id
        )
        assert annotation.scope == AnnotationScope.PROJECT
        assert annotation.created_by_id == self.user.id
        assert annotation.organization_id == self.organization.id
        assert annotation.date_marker is not None

    @parameterized.expand(
        [
            ("dashboard_of_another_team", "dashboard_id", "other_team_dashboard", "Dashboard not found."),
            ("soft_deleted_insight", "insight_id", "deleted_insight", "Insight not found."),
            (
                "insight_scope_without_insight",
                "insight_id",
                None,
                "Set `dashboard_item` to the insight ID when the scope is `dashboard_item`.",
            ),
        ]
    )
    def test_create_enforces_parent_rules_for_every_caller(
        self, _name: str, field: str, parent: str | None, message: str
    ) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        parents = {
            "other_team_dashboard": Dashboard.objects.create(team=other_team).id,
            "deleted_insight": Insight.objects.create(team=self.team, deleted=True).id,
        }
        parent_id = parents[parent] if parent else None
        write = AnnotationWrite(
            fields_set=frozenset({"scope", field}),
            scope=AnnotationScope.DASHBOARD if field == "dashboard_id" else AnnotationScope.INSIGHT,
            dashboard_id=parent_id if field == "dashboard_id" else None,
            insight_id=parent_id if field == "insight_id" else None,
        )

        with self.assertRaises(AnnotationWriteRejectedError) as rejected:
            api.create_annotation(
                team_id=self.team.id, organization_id=self.organization.id, created_by_id=self.user.id, write=write
            )

        assert (rejected.exception.field, rejected.exception.message) == (field, message)
        assert not Annotation.objects.exists()

    def test_annotation_ids_in_team_ignores_other_teams(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        own = Annotation.objects.create(team=self.team, deleted=True)
        foreign = Annotation.objects.create(team=other_team)

        assert api.annotation_ids_in_team(team_id=self.team.id, annotation_ids=[own.id, foreign.id]) == {own.id}
