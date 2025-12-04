from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models.surveys.survey_recommendation import SurveyRecommendation


class TestSurveyRecommendation(APIBaseTest):
    def _create_recommendation(self, **kwargs) -> SurveyRecommendation:
        defaults = {
            "team": self.team,
            "recommendation_type": SurveyRecommendation.RecommendationType.LOW_CONVERSION_FUNNEL,
            "survey_defaults": {"name": "Test Survey", "type": "popover", "questions": []},
            "display_context": {"title": "Test", "description": "Test"},
            "score": 0.5,
        }
        defaults.update(kwargs)
        return SurveyRecommendation.objects.create(**defaults)

    def test_list_filters_to_active_by_default(self):
        active = self._create_recommendation()
        self._create_recommendation(status=SurveyRecommendation.Status.DISMISSED)

        response = self.client.get(f"/api/projects/{self.team.id}/survey_recommendations/")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) == 1
        assert response.json()["results"][0]["id"] == str(active.id)

    def test_patch_to_dismiss_sets_dismissed_at(self):
        rec = self._create_recommendation()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/survey_recommendations/{rec.id}/",
            data={"status": "dismissed"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        rec.refresh_from_db()
        assert rec.status == SurveyRecommendation.Status.DISMISSED
        assert rec.dismissed_at is not None

    def test_patch_rejects_invalid_status(self):
        rec = self._create_recommendation()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/survey_recommendations/{rec.id}/",
            data={"status": "active"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
