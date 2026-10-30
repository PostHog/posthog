from posthog.test.base import APIBaseTest

from django.core.cache import cache

from parameterized import parameterized
from rest_framework import status

from posthog.temporal.ai_observability.clustering_skip_status import ClusteringLevel, record_not_enough_items

from products.ai_observability.backend.models.clustering_job import ClusteringJob


class TestClusteringSkipReason(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

    def _get(self, analysis_level: str):
        return self.client.get(
            f"/api/projects/{self.team.id}/llm_analytics/clustering_runs/skip_reason/",
            {"analysis_level": analysis_level},
        )

    @parameterized.expand(
        [
            ("no_consent_wins_over_recorded_skip", False, ["trace"], True, "trace", "ai_data_processing_not_approved"),
            ("job_only_at_other_level", True, ["trace"], False, "generation", "no_enabled_job"),
            ("evaluation_needs_its_own_job", True, [], False, "evaluation", "no_enabled_job"),
            ("legacy_fallback_without_jobs", True, [], False, "trace", "not_scheduled"),
            ("recorded_skip", True, ["trace"], True, "trace", "not_enough_items"),
        ]
    )
    def test_skip_reason(
        self,
        _name: str,
        consent: bool,
        job_levels: list[str],
        recorded_skip: bool,
        analysis_level: ClusteringLevel,
        expected_reason: str,
    ) -> None:
        self.organization.is_ai_data_processing_approved = consent
        self.organization.save()
        ClusteringJob.objects.filter(team=self.team).delete()
        for level in job_levels:
            ClusteringJob.objects.create(team=self.team, name=f"Job {level}", analysis_level=level)
        if recorded_skip:
            record_not_enough_items(self.team.id, analysis_level, item_count=240, min_required=1000)

        response = self._get(analysis_level)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["reason"] == expected_reason
        if expected_reason == "not_enough_items":
            assert (response.json()["item_count"], response.json()["min_required"]) == (240, 1000)

    def test_rejects_unknown_level(self) -> None:
        assert self._get("session").status_code == status.HTTP_400_BAD_REQUEST
