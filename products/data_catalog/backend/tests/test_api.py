from posthog.test.base import APIBaseTest

from django.db import connection
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized
from rest_framework import status

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team import Team
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.data_catalog.backend.facade.enums import MetricStatus
from products.data_catalog.backend.logic.metrics import upsert_metric
from products.data_catalog.backend.models import Metric
from products.product_analytics.backend.models.insight import Insight

_HOGQL = {"kind": "HogQLQuery", "query": "select count() from events"}


class TestMetricAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/data_catalog/metrics/"

    def test_create_lands_proposed(self) -> None:
        response = self.client.post(self.url, {"name": "mrr", "description": "Monthly revenue"}, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        body = response.json()
        assert body["name"] == "mrr"
        assert body["status"] == MetricStatus.PROPOSED

    def test_status_and_approval_are_not_writable(self) -> None:
        response = self.client.post(
            self.url,
            {"name": "mrr", "description": "d", "status": "approved", "approved_at": "2020-01-01T00:00:00Z"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["status"] == MetricStatus.PROPOSED
        assert response.json()["approved_at"] is None

    def test_create_is_upsert_on_name(self) -> None:
        self.client.post(self.url, {"name": "mrr", "description": "v1"}, format="json")
        response = self.client.post(self.url, {"name": "mrr", "description": "v2"}, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        assert Metric.objects.for_team(self.team.id).count() == 1
        assert self.client.get(f"{self.url}mrr/").json()["description"] == "v2"

    def test_refine_via_post_preserves_omitted_definition(self) -> None:
        definition = {"kind": "HogQLQuery", "query": "select count() from events"}
        self.client.post(self.url, {"name": "mrr", "description": "v1", "definition": definition}, format="json")
        response = self.client.post(self.url, {"name": "mrr", "description": "v2"}, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        body = self.client.get(f"{self.url}mrr/").json()
        assert body["description"] == "v2"
        assert body["definition"]["kind"] == "HogQLQuery"
        assert body["referenced_table_names"] == ["events"]

    def test_name_addressed_detail_routes(self) -> None:
        self.client.post(self.url, {"name": "mrr", "description": "v1"}, format="json")

        assert self.client.get(f"{self.url}mrr/").status_code == status.HTTP_200_OK

        patched = self.client.patch(f"{self.url}mrr/", {"display_name": "MRR"}, format="json")
        assert patched.status_code == status.HTTP_200_OK
        assert patched.json()["display_name"] == "MRR"

        assert self.client.delete(f"{self.url}mrr/").status_code == status.HTTP_204_NO_CONTENT
        assert self.client.get(f"{self.url}mrr/").status_code == status.HTTP_404_NOT_FOUND

    def test_patch_cannot_change_name(self) -> None:
        self.client.post(self.url, {"name": "mrr", "description": "v1"}, format="json")
        response = self.client.patch(f"{self.url}mrr/", {"name": "arr"}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_definition_rejected(self) -> None:
        response = self.client.post(
            self.url,
            {"name": "mrr", "description": "d", "definition": {"kind": "RetentionQuery"}},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_markdown_definition_accepted(self) -> None:
        response = self.client.post(
            self.url,
            {
                "name": "activation",
                "description": "Activated users",
                "definition": {"kind": "MarkdownDefinition", "markdown": "1. User did A then B within 7 days."},
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["definition_kind"] == "MarkdownDefinition"

    def test_list_is_team_scoped(self) -> None:
        other_team = Team.objects.create_with_data(
            organization=self.organization, initiating_user=self.user, name="Other"
        )
        self.client.post(self.url, {"name": "mine", "description": "d"}, format="json")
        Metric.objects.for_team(other_team.id).create(team=other_team, name="theirs", description="d")

        names = [row["name"] for row in self.client.get(self.url).json()["results"]]
        assert names == ["mine"]


class TestMetricLifecycleAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/data_catalog/metrics/"

    def _insight(self, query: dict | None = None) -> Insight:
        return Insight.objects.create(team=self.team, created_by=self.user, query=query or _HOGQL)

    def test_session_user_can_approve(self) -> None:
        upsert_metric(team=self.team, user=self.user, name="mrr", description="d", definition=_HOGQL)
        response = self.client.post(f"{self.url}mrr/approve/")
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["status"] == MetricStatus.APPROVED

    def test_create_from_insight_snapshots_definition(self) -> None:
        insight = self._insight()
        response = self.client.post(
            self.url, {"name": "mrr", "description": "d", "source_insight_short_id": insight.short_id}, format="json"
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        body = response.json()
        assert body["definition"]["kind"] == "HogQLQuery"
        assert body["is_drifted"] is False

    def test_list_computes_drift_in_a_single_insight_query(self) -> None:
        # is_drifted must not fan out into one insight lookup per metric: the list view precomputes
        # drift for the whole page in one bulk query. Three linked metrics => one insight query.
        for i in range(3):
            insight = self._insight()
            self.client.post(
                self.url,
                {"name": f"m{i}", "description": "d", "source_insight_short_id": insight.short_id},
                format="json",
            )
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        insight_queries = [q for q in ctx.captured_queries if "posthog_dashboarditem" in q["sql"]]
        assert len(insight_queries) == 1, insight_queries

    def test_approve_returns_409_while_drifted(self) -> None:
        insight = self._insight()
        self.client.post(
            self.url, {"name": "mrr", "description": "d", "source_insight_short_id": insight.short_id}, format="json"
        )
        Insight.objects.filter(pk=insight.pk).update(
            query={"kind": "HogQLQuery", "query": "select count() from persons"}
        )
        assert self.client.get(f"{self.url}mrr/").json()["is_drifted"] is True
        assert self.client.post(f"{self.url}mrr/approve/").status_code == status.HTTP_409_CONFLICT

    def test_refresh_then_approve_succeeds(self) -> None:
        insight = self._insight()
        self.client.post(
            self.url, {"name": "mrr", "description": "d", "source_insight_short_id": insight.short_id}, format="json"
        )
        Insight.objects.filter(pk=insight.pk).update(
            query={"kind": "HogQLQuery", "query": "select count() from persons"}
        )
        assert self.client.post(f"{self.url}mrr/refresh_from_insight/").status_code == status.HTTP_200_OK
        assert self.client.post(f"{self.url}mrr/approve/").status_code == status.HTTP_200_OK

    def _bearer(self, scopes: list[str]) -> dict:
        raw = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="k", user=self.user, secure_value=hash_key_value(raw), scopes=scopes)
        return {"HTTP_AUTHORIZATION": f"Bearer {raw}"}

    @parameterized.expand(
        [
            ("without_approval_scope", ["data_catalog:read", "data_catalog:write"], status.HTTP_403_FORBIDDEN),
            ("approval_scope_only", ["data_catalog_approval:write"], status.HTTP_403_FORBIDDEN),
            (
                "with_approval_scope",
                ["data_catalog:read", "data_catalog:write", "data_catalog_approval:write"],
                status.HTTP_200_OK,
            ),
        ]
    )
    def test_token_needs_approval_scope_to_approve(self, _name: str, scopes: list[str], expected: int) -> None:
        upsert_metric(team=self.team, user=self.user, name="mrr", description="d", definition=_HOGQL)
        self.client.logout()  # force the personal API key authenticator, not the session
        response = self.client.post(f"{self.url}mrr/approve/", **self._bearer(scopes))
        assert response.status_code == expected, response.json()

    @parameterized.expand(
        [
            ("without_insight_read", ["data_catalog:read", "data_catalog:write"], status.HTTP_403_FORBIDDEN),
            (
                "with_insight_read",
                ["data_catalog:read", "data_catalog:write", "insight:read"],
                status.HTTP_201_CREATED,
            ),
        ]
    )
    def test_create_from_insight_needs_insight_read_scope(self, _name: str, scopes: list[str], expected: int) -> None:
        insight = self._insight()
        self.client.logout()
        response = self.client.post(
            self.url,
            {"name": "mrr", "description": "d", "source_insight_short_id": insight.short_id},
            format="json",
            **self._bearer(scopes),
        )
        assert response.status_code == expected, response.json()

    @parameterized.expand(
        [
            ("without_insight_read", ["data_catalog:read", "data_catalog:write"], status.HTTP_403_FORBIDDEN),
            ("with_insight_read", ["data_catalog:read", "data_catalog:write", "insight:read"], status.HTTP_200_OK),
        ]
    )
    def test_refresh_from_insight_needs_insight_read_scope(self, _name: str, scopes: list[str], expected: int) -> None:
        insight = self._insight()
        upsert_metric(
            team=self.team, user=self.user, name="mrr", description="d", source_insight_short_id=insight.short_id
        )
        self.client.logout()
        response = self.client.post(f"{self.url}mrr/refresh_from_insight/", **self._bearer(scopes))
        assert response.status_code == expected, response.json()

    def test_plain_create_does_not_need_insight_scope(self) -> None:
        self.client.logout()
        response = self.client.post(
            self.url, {"name": "mrr", "description": "d"}, format="json", **self._bearer(["data_catalog:write"])
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
