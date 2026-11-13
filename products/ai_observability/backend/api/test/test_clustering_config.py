from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models import Team

from products.ai_observability.backend.models.clustering_config import ClusteringConfig
from products.ai_observability.backend.models.clustering_job import ClusteringJob
from products.ai_observability.backend.models.clustering_run import ClusteringRun


class TestClusteringConfigViewSet(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])

    def test_enabling_immediately_dispatches_one_run_per_job_and_reuses_queued_runs(self):
        url = f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_enabled/"
        with patch("products.ai_observability.backend.temporal.clustering_client.dispatch_clustering_run") as dispatch:
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(self.client.post(url, {"enabled": True}, format="json").status_code, 200)
            self.assertEqual(dispatch.call_count, 3)
            first_ids = set(ClusteringRun.objects.for_team(self.team.id).values_list("id", flat=True))
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(url, {"enabled": False}, format="json")
                self.client.post(url, {"enabled": True}, format="json")
            self.assertEqual(set(ClusteringRun.objects.for_team(self.team.id).values_list("id", flat=True)), first_ids)
            self.assertEqual({call.args[1] for call in dispatch.call_args_list}, {str(id) for id in first_ids})

    def test_enable_requires_ai_processing_consent(self):
        self.organization.is_ai_data_processing_approved = False
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_enabled/",
            {"enabled": True},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(ClusteringRun.objects.for_team(self.team.id).exists())

    def test_progress_separates_jobs_and_retry_preserves_the_previous_attempt(self):
        self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_enabled/",
            {"enabled": True},
            format="json",
        )
        run = ClusteringRun.objects.for_team(self.team.id).get(job__analysis_level="trace")
        run.status = "failed"
        run.eligible_count = 10
        run.save()
        progress_url = f"/api/environments/{self.team.id}/llm_analytics/clustering_config/progress/"
        data = self.client.get(progress_url).data
        self.assertEqual(len(data), 3)
        self.assertEqual({job["minimum"] for job in data}, {10})
        self.assertEqual(
            {job["analysis_level"]: job["lookback_days"] for job in data},
            {"trace": 7, "generation": 7, "evaluation": 3},
        )
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_config/retry/",
            {"job_id": str(run.job_id)},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        run.refresh_from_db()
        self.assertEqual(run.status, "failed")
        self.assertEqual(ClusteringRun.objects.for_team(self.team.id).filter(job=run.job, status="queued").count(), 1)

    def test_progress_and_retry_are_scoped_to_the_project(self):
        other_team = Team.objects.create(organization=self.organization, name="Another project")
        other_job = ClusteringJob.objects.create(team=other_team, name="Other traces", analysis_level="trace")
        ClusteringConfig.objects.create(team=self.team, enabled=True)
        self.assertEqual(
            self.client.get(f"/api/environments/{self.team.id}/llm_analytics/clustering_config/progress/").data, []
        )
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_config/retry/",
            {"job_id": str(other_job.id)},
            format="json",
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(ClusteringRun.objects.for_team(other_team.id).exists())

    def test_projects_are_off_until_explicitly_enabled(self):
        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/clustering_config/")
        self.assertFalse(response.data["enabled"])
        self.assertFalse(ClusteringJob.objects.filter(team=self.team).exists())

        url = f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_enabled/"
        for _ in range(2):
            response = self.client.post(url, {"enabled": True}, format="json")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertTrue(response.data["enabled"])
        self.assertCountEqual(
            ClusteringJob.objects.filter(team=self.team, enabled=True).values_list("analysis_level", flat=True),
            ["trace", "generation", "evaluation"],
        )

    def test_disable_and_reenable_preserve_custom_jobs_and_filters(self):
        filters = [{"key": "$ai_model", "value": "gpt-4", "operator": "exact", "type": "event"}]
        ClusteringConfig.objects.create(team=self.team, enabled=True, event_filters=filters)
        job = ClusteringJob.objects.create(
            team=self.team, name="Production traces", analysis_level="trace", event_filters=filters
        )
        url = f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_enabled/"
        response = self.client.post(url, {"enabled": False}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["enabled"])
        self.assertEqual(response.data["event_filters"], filters)
        job.refresh_from_db()
        self.assertTrue(job.enabled)
        self.client.post(url, {"enabled": True}, format="json")
        self.assertEqual(ClusteringJob.objects.filter(team=self.team, analysis_level="trace").count(), 1)
        job.refresh_from_db()
        self.assertEqual(job.event_filters, filters)

    def test_set_enabled_requires_a_boolean(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_enabled/",
            {"enabled": "please"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(ClusteringConfig.objects.filter(team=self.team, enabled=True).exists())

    def test_unauthenticated_user_cannot_access_config(self):
        self.client.logout()
        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/clustering_config/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_can_get_clustering_config(self):
        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/clustering_config/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertIn("event_filters", response.data)
        self.assertIn("created_at", response.data)
        self.assertIn("updated_at", response.data)
        self.assertEqual(response.data["event_filters"], [])

    def test_get_creates_config_if_missing(self):
        self.assertEqual(ClusteringConfig.objects.filter(team=self.team).count(), 0)

        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/clustering_config/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(ClusteringConfig.objects.filter(team=self.team).count(), 1)

    def test_get_returns_existing_config(self):
        ClusteringConfig.objects.create(
            team=self.team,
            event_filters=[{"key": "ai_product", "value": "posthog_ai", "operator": "exact", "type": "event"}],
        )

        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/clustering_config/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["event_filters"]), 1)
        self.assertEqual(response.data["event_filters"][0]["key"], "ai_product")

    def test_can_set_event_filters(self):
        filters = [{"key": "$ai_model", "value": "gpt-4", "operator": "exact", "type": "event"}]

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_event_filters/",
            {"event_filters": filters},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["event_filters"], filters)

        config = ClusteringConfig.objects.get(team=self.team)
        self.assertEqual(config.event_filters, filters)

    def test_can_clear_event_filters(self):
        ClusteringConfig.objects.create(
            team=self.team,
            event_filters=[{"key": "ai_product", "value": "posthog_ai", "operator": "exact", "type": "event"}],
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_event_filters/",
            {"event_filters": []},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["event_filters"], [])

    def test_set_event_filters_requires_event_filters_field(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_event_filters/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("event_filters", response.data["detail"].lower())

    def test_set_event_filters_rejects_non_list(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_event_filters/",
            {"event_filters": "not a list"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("list", response.data["detail"].lower())

    def test_set_event_filters_persists_across_requests(self):
        filters = [
            {"key": "ai_product", "value": "posthog_ai", "operator": "exact", "type": "event"},
            {"key": "$ai_model", "value": "gpt-4", "operator": "exact", "type": "event"},
        ]

        self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_event_filters/",
            {"event_filters": filters},
            format="json",
        )

        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/clustering_config/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["event_filters"]), 2)

    # The default test client uses force_login, which skips the scope check, so these
    # cases use a real Personal API Key — the path MCP and OAuth callers take — to lock
    # the scope the MCP tools must declare (ai_observability_clusters, not llm_analytics).
    @parameterized.expand(
        [
            ("correct_read_scope", ["ai_observability_clusters:read"], status.HTTP_200_OK),
            ("write_scope_grants_read", ["ai_observability_clusters:write"], status.HTTP_200_OK),
            ("wrong_scope_denied", ["llm_analytics:read"], status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_get_config_pak_scope(self, _name: str, scopes: list[str], expected_status: int) -> None:
        api_key = self.create_personal_api_key_with_scopes(scopes)
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/clustering_config/")
        self.assertEqual(response.status_code, expected_status)

    # set_event_filters carries its own required_scopes override rather than inheriting
    # scope_object, so it needs separate coverage from the list action above.
    @parameterized.expand(
        [
            ("correct_write_scope", ["ai_observability_clusters:write"], status.HTTP_200_OK),
            ("read_scope_denied", ["ai_observability_clusters:read"], status.HTTP_403_FORBIDDEN),
            ("wrong_scope_denied", ["llm_analytics:write"], status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_set_event_filters_pak_scope(self, _name: str, scopes: list[str], expected_status: int) -> None:
        api_key = self.create_personal_api_key_with_scopes(scopes)
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_event_filters/",
            {"event_filters": []},
            format="json",
        )
        self.assertEqual(response.status_code, expected_status)
