import pytest
from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import Team, User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.organization import OrganizationMembership

from products.access_control.backend.models.access_control import AccessControl
from products.ai_observability.backend.models.evaluation_directories import EvaluationDirectory
from products.ai_observability.backend.models.evaluations import Evaluation


class TestEvaluationDirectoriesApi(APIBaseTest):
    def _create_directory(self, name: str = "Quality") -> EvaluationDirectory:
        return EvaluationDirectory.objects.for_team(self.team.id).create(
            team=self.team,
            name=name,
            created_by=self.user,
        )

    def _create_evaluation(self, name: str = "Correctness") -> Evaluation:
        return Evaluation.objects.create(
            team=self.team,
            name=name,
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Check correctness"},
            output_type="boolean",
            created_by=self.user,
        )

    def test_names_are_trimmed_and_unique_ignoring_case(self) -> None:
        url = f"/api/projects/{self.team.id}/evaluation_directories/"

        created = self.client.post(url, {"name": "  Quality  "}, format="json")
        duplicate = self.client.post(url, {"name": "quality"}, format="json")

        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertEqual(created.json()["name"], "Quality")
        self.assertEqual(duplicate.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(EvaluationDirectory.objects.for_team(self.team.id).count(), 1)

    def test_evaluation_can_move_into_a_directory_and_back_to_the_top_level(self) -> None:
        directory = self._create_directory()
        evaluation = self._create_evaluation()
        url = f"/api/projects/{self.team.id}/evaluations/{evaluation.id}/"

        moved = self.client.patch(url, {"directory_id": str(directory.id)}, format="json")
        moved_to_top_level = self.client.patch(url, {"directory_id": None}, format="json")

        self.assertEqual(moved.status_code, status.HTTP_200_OK)
        self.assertEqual(moved.json()["directory_id"], str(directory.id))
        self.assertEqual(moved_to_top_level.status_code, status.HTTP_200_OK)
        self.assertIsNone(moved_to_top_level.json()["directory_id"])

    def test_evaluation_cannot_move_to_another_teams_directory(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        other_directory = EvaluationDirectory.objects.for_team(other_team.id).create(
            team=other_team,
            name="Other directory",
        )
        evaluation = self._create_evaluation()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/evaluations/{evaluation.id}/",
            {"directory_id": str(other_directory.id)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        evaluation.refresh_from_db()
        self.assertIsNone(evaluation.directory_id)

    def test_deleting_a_directory_moves_its_evaluations_to_the_top_level(self) -> None:
        directory = self._create_directory()
        active_evaluation = self._create_evaluation("Active")
        deleted_evaluation = self._create_evaluation("Deleted")
        Evaluation.objects.filter(id__in=[active_evaluation.id, deleted_evaluation.id]).update(directory=directory)
        Evaluation.objects.filter(id=deleted_evaluation.id).update(deleted=True)
        active_evaluation.refresh_from_db()
        previous_updated_at = active_evaluation.updated_at
        ActivityLog.objects.filter(team_id=self.team.id).delete()

        listed = self.client.get(f"/api/projects/{self.team.id}/evaluation_directories/")
        response = self.client.delete(f"/api/projects/{self.team.id}/evaluation_directories/{directory.id}/")

        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        self.assertEqual(listed.json()[0]["evaluation_count"], 1)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(EvaluationDirectory.objects.for_team(self.team.id).filter(id=directory.id).exists())
        self.assertEqual(
            Evaluation.objects.filter(id__in=[active_evaluation.id, deleted_evaluation.id], directory=None).count(),
            2,
        )
        active_evaluation.refresh_from_db()
        self.assertGreater(active_evaluation.updated_at, previous_updated_at)
        self.assertTrue(
            ActivityLog.objects.filter(
                team_id=self.team.id,
                scope="Evaluation",
                item_id=str(active_evaluation.id),
                activity="updated",
                detail__changes__contains=[{"field": "directory", "action": "deleted"}],
            ).exists()
        )
        self.assertTrue(
            ActivityLog.objects.filter(
                team_id=self.team.id,
                scope="EvaluationDirectory",
                item_id=str(directory.id),
                activity="deleted",
            ).exists()
        )

    def test_evaluations_can_be_filtered_to_the_top_level(self) -> None:
        directory = self._create_directory()
        top_level_evaluation = self._create_evaluation("Top level")
        directory_evaluation = self._create_evaluation("In directory")
        Evaluation.objects.filter(id=directory_evaluation.id).update(directory=directory)

        response = self.client.get(
            f"/api/projects/{self.team.id}/evaluations/",
            {"directory_id__isnull": "true"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([result["id"] for result in response.json()["results"]], [str(top_level_evaluation.id)])

    @pytest.mark.ee
    def test_specific_evaluation_access_does_not_authorize_directory_changes(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()

        limited_user = User.objects.create_and_join(self.organization, "limited@posthog.com", "testpassword123")
        directory = EvaluationDirectory.objects.for_team(self.team.id).create(
            team=self.team,
            name="Restricted",
            created_by=self.user,
        )
        evaluation = self._create_evaluation()
        membership = OrganizationMembership.objects.get(user=limited_user, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="evaluation",
            access_level="none",
            organization_member=membership,
        )
        AccessControl.objects.create(
            team=self.team,
            resource="evaluation",
            resource_id=str(evaluation.id),
            access_level="editor",
            organization_member=membership,
        )
        self.client.force_login(limited_user)

        renamed = self.client.patch(
            f"/api/projects/{self.team.id}/evaluation_directories/{directory.id}/",
            {"name": "Renamed"},
            format="json",
        )
        deleted = self.client.delete(f"/api/projects/{self.team.id}/evaluation_directories/{directory.id}/")

        self.assertEqual(renamed.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(deleted.status_code, status.HTTP_403_FORBIDDEN)
