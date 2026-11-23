from posthog.test.base import APIBaseTest
from unittest.mock import patch

from posthog.models import OrganizationMembership, Team
from posthog.models.project_secret_api_key import ProjectSecretAPIKey

from products.ai_observability.backend.dataset_export import DatasetExportError, export_dataset_jsonl
from products.ai_observability.backend.presentation.views.trace_ids import encode_trace_id_segment
from products.exports.backend.facade.api import get_export_asset


class TestAIObservabilityProjectKeys(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.project_url = f"/api/projects/{self.team.id}"

    def _issue(self, label: str, scopes: list[str]) -> dict:
        self.client.credentials()
        self.client.force_login(self.user)
        response = self.client.post(f"{self.project_url}/project_secret_api_keys/", {"label": label, "scopes": scopes})
        assert response.status_code == 201, response.data
        assert response.data["scopes"] == scopes
        return response.data

    def _use(self, key: dict) -> None:
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {key['value']}")

    def test_scorer_and_trace_score_share_project_grants(self) -> None:
        writer = self._issue("Review writer", ["ai_observability:write"])
        reader = self._issue("Review reader", ["ai_observability:read"])
        self._use(writer)
        scorers = f"{self.project_url}/llm_analytics/score_definitions/"
        reviews = f"{self.project_url}/llm_analytics/trace_reviews/"
        definition = self.client.post(
            scorers,
            {"name": "Accurate", "kind": "boolean", "config": {"true_label": "Yes", "false_label": "No"}},
            format="json",
        )
        assert definition.status_code == 201, definition.data
        assert definition.data["created_by"] is None
        trace_id = "scored-trace"
        review = self.client.post(
            reviews,
            {"trace_id": trace_id, "scores": [{"definition_id": definition.data["id"], "boolean_value": True}]},
            format="json",
        )
        assert review.status_code == 201, review.data
        assert review.data["reviewed_by"] is None
        url = f"{reviews}{review.data['id']}/"
        self._use(reader)
        assert self.client.get(url).data["scores"][0]["boolean_value"] is True
        rendered = self.client.get(
            f"{self.project_url}/ai_observability/traces/{encode_trace_id_segment(trace_id)}/review/"
        )
        assert rendered.status_code == 200, rendered.data
        denied = self.client.delete(url)
        assert denied.status_code == 403
        assert "ai_observability:write" in denied.data["detail"]
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        assert self.client.get(f"/api/projects/{other_team.id}/llm_analytics/trace_reviews/").status_code == 403
        assert self.client.get(f"{self.project_url}/ai_observability/offline_experiments/").status_code == 403
        self._use(writer)
        assert self.client.delete(url).status_code == 204

    def test_dataset_snapshot_and_export_belong_to_the_issuing_project_and_requesting_key(self) -> None:
        writer = self._issue("Dataset writer", ["dataset:write"])
        reader = self._issue("Dataset reader", ["dataset:read"])
        self._use(writer)
        datasets = f"{self.project_url}/datasets/"
        items = f"{self.project_url}/dataset_items/"
        with patch("posthog.permissions.posthog_feature_flag_enabled", return_value=True):
            dataset = self.client.post(datasets, {"name": "Project key dataset"})
            assert dataset.status_code == 201, dataset.data
            dataset_id = dataset.data["id"]
            item = self.client.post(items, {"dataset": dataset_id, "input": "First item"}, format="json")
            assert item.status_code == 201, item.data
            self._use(reader)
            assert self.client.post(datasets, {"name": "Read only"}).status_code == 403
            snapshot = self.client.get(items, {"dataset": dataset_id, "revision": item.data["dataset_revision"]})
            assert snapshot.status_code == 200, snapshot.data
            assert snapshot.data["results"][0]["id"] == item.data["id"]
            exports = f"{datasets}{dataset_id}/exports/"
            receipt = self.client.post(exports, {}, format="json")
            assert receipt.status_code == 201, receipt.data
            export_id = receipt.data["id"]
            url = f"{exports}{export_id}/"
            assert self.client.get(url).status_code == 200
            self._use(writer)
            assert self.client.get(url).status_code == 404
            assert self.client.get(f"{url}content/").status_code == 404
        asset = get_export_asset(team_id=self.team.id, asset_id=export_id)
        assert asset is not None
        assert asset.created_by_id is None
        assert asset.export_context["project_key_id"] == reader["id"]
        with patch("products.ai_observability.backend.dataset_export.posthog_feature_flag_value", return_value=True):
            export_dataset_jsonl(asset)
        ProjectSecretAPIKey.objects.filter(id=reader["id"]).update(scopes=["evaluation:read"])
        with self.assertRaisesRegex(DatasetExportError, "no longer have access"):
            export_dataset_jsonl(asset)
