from contextlib import nullcontext

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, Team
from posthog.test import access_control_checks

from products.annotations.backend.api.annotation import AnnotationSerializer
from products.dashboards.backend.models.dashboard import Dashboard
from products.surveys.backend.api.survey import SurveyViewSet
from products.surveys.backend.models import Survey


class TestAccessControlChecks(APIBaseTest):
    def _problems(self) -> list[str]:
        problems = access_control_checks.finish_test()
        access_control_checks.start_test()
        return problems

    @parameterized.expand([("checked", False), ("unchecked", True)])
    def test_reports_a_referenced_object_loaded_without_a_check(self, _name: str, skip_check: bool) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="Referenced")

        skipped = patch.object(AnnotationSerializer, "_require_viewer_access", lambda *args: None)
        with skipped if skip_check else nullcontext():
            response = self.client.post(
                f"/api/projects/{self.team.id}/annotations/",
                {
                    "content": "x",
                    "scope": "dashboard",
                    "date_marker": "2024-01-01T00:00:00Z",
                    "dashboard_id": dashboard.id,
                },
                format="json",
            )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        problems = self._problems()
        assert bool(problems) == skip_check, problems
        if skip_check:
            assert f"AnnotationsViewSet.create loaded Dashboard {dashboard.id}" in problems[0]

    def test_reports_a_detail_action_without_an_object_check(self) -> None:
        survey = Survey.objects.create(team=self.team, name="Survey", type="popover", questions=[])

        with patch.object(SurveyViewSet, "check_object_permissions", lambda *args: None):
            response = self.client.get(f"/api/projects/{self.team.id}/surveys/{survey.id}/")

        assert response.status_code == status.HTTP_200_OK
        problems = self._problems()
        assert len(problems) == 1 and problems[0].startswith("SurveyViewSet.retrieve succeeded without"), problems

    def test_reports_a_foreign_key_into_another_project(self) -> None:
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other"), name="Other")
        foreign = Dashboard.objects.create(team=other_team, name="Foreign")

        with patch.object(AnnotationSerializer, "validate", lambda self, attrs: attrs):
            self.client.post(
                f"/api/projects/{self.team.id}/annotations/",
                {
                    "content": "x",
                    "scope": "dashboard",
                    "date_marker": "2024-01-01T00:00:00Z",
                    "dashboard_id": foreign.id,
                },
                format="json",
            )

        problems = self._problems()
        assert any(problem.startswith("Annotation.dashboard points at Dashboard") for problem in problems), problems
