from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.db import connection
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team import Team
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.rate_limit import ClickHouseBurstRateThrottle, HogQLQueryThrottle

from products.data_catalog.backend.facade.enums import MetricStatus
from products.data_catalog.backend.logic.metrics import (
    BULK_SKIP_ALREADY_APPROVED,
    BULK_SKIP_DRIFTED,
    BULK_SKIP_NOT_FOUND,
    METRIC_BULK_MAX,
    approve_metric,
    soft_delete_metric,
    upsert_metric,
)
from products.data_catalog.backend.models import Metric
from products.data_catalog.backend.presentation.serializers import (
    MetricBulkNamesRequestSerializer,
    MetricRunQuerySerializer,
    MetricRunRequestSerializer,
    MetricSerializer,
)
from products.product_analytics.backend.facade.models import Insight

from ee.models.rbac.access_control import AccessControl

_HOGQL = {"kind": "HogQLQuery", "query": "select count() from events"}
_PROCESS_QUERY = "products.data_catalog.backend.logic.execution.process_query_dict"


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

    def test_overlong_description_rejected(self) -> None:
        response = self.client.post(self.url, {"name": "mrr", "description": "x" * 1_001}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "description"

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

    def test_patch_renames_metric(self) -> None:
        self.client.post(self.url, {"name": "mrr", "description": "v1"}, format="json")
        response = self.client.patch(f"{self.url}mrr/", {"name": "arr"}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["name"] == "arr"
        assert self.client.get(f"{self.url}mrr/").status_code == status.HTTP_404_NOT_FOUND
        assert self.client.get(f"{self.url}arr/").status_code == status.HTTP_200_OK

    def test_create_after_delete_starts_fresh(self) -> None:
        created = self.client.post(
            self.url, {"name": "mrr", "description": "v1", "definition": _HOGQL}, format="json"
        ).json()
        self.client.delete(f"{self.url}mrr/")

        response = self.client.post(self.url, {"name": "mrr", "description": "v2"}, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        body = response.json()
        assert body["id"] != created["id"]
        assert body["definition"] is None

    def test_invalid_definition_rejected(self) -> None:
        response = self.client.post(
            self.url,
            {"name": "mrr", "description": "d", "definition": {"kind": "RetentionQuery"}},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        # The agent-facing envelope must carry the actual problem, not just the field name.
        body = response.json()
        assert body["attr"] == "definition"
        assert "Unsupported definition kind" in body["detail"]

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

    def test_run_without_definition_returns_400(self) -> None:
        self.client.post(self.url, {"name": "mrr", "description": "stub only"}, format="json")
        response = self.client.post(f"{self.url}mrr/run/")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_run_rejects_date_params_on_hogql_metric(self) -> None:
        upsert_metric(team=self.team, user=self.user, name="mrr", description="d", definition=_HOGQL)
        response = self.client.post(f"{self.url}mrr/run/", {"date_from": "-7d"}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["attr"] == "date_from"
        assert "fixed in its SQL" in body["detail"]

    def test_run_requires_query_read_scope(self) -> None:
        upsert_metric(team=self.team, user=self.user, name="mrr", description="d", definition=_HOGQL)
        self.client.logout()
        # data_catalog:read alone is not enough — run also touches the query engine.
        response = self.client.post(f"{self.url}mrr/run/", **self._bearer(["data_catalog:read"]))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_run_denied_for_session_user_without_query_access(self) -> None:
        # Session users carry no API scopes, so required_scopes can't gate them and
        # AccessControlPermission only checks the data_catalog resource. A member with query
        # access explicitly set to "none" must still be blocked from reading data through a run.
        upsert_metric(team=self.team, user=self.user, name="mrr", description="d", definition=_HOGQL)
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save(update_fields=["level"])
        AccessControl.objects.create(
            team=self.team,
            resource="query",
            resource_id=None,
            organization_member=self.organization_membership,
            access_level="none",
        )
        cache.clear()
        response = self.client.post(f"{self.url}mrr/run/")
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()

    def test_run_markdown_metric_returns_instructions(self) -> None:
        upsert_metric(
            team=self.team,
            user=self.user,
            name="activation",
            description="d",
            definition={"kind": "MarkdownDefinition", "markdown": "1. User did A then B within 7 days."},
        )
        response = self.client.post(f"{self.url}activation/run/")
        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert body["kind"] == "MarkdownDefinition"
        assert body["results"] is None
        assert "A then B" in body["instructions"]

    @parameterized.expand(
        [
            ("invalid_interval_in_body", {"interval": "fortnight"}, ""),
            ("invalid_refresh_query_param", {}, "?refresh=nope"),
        ]
    )
    def test_run_rejects_malformed_input(self, _name: str, body: dict, query_string: str) -> None:
        # Wiring guard: the run action must validate through its serializers, so malformed input
        # never reaches the query engine. The value matrix lives in TestMetricRunInputValidation.
        upsert_metric(team=self.team, user=self.user, name="mrr", description="d", definition=_HOGQL)
        response = self.client.post(f"{self.url}mrr/run/{query_string}", body, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def _drifted_metric(self, name: str) -> Metric:
        insight = self._insight()
        metric = upsert_metric(
            team=self.team, user=self.user, name=name, description="d", source_insight_short_id=insight.short_id
        )
        Insight.objects.filter(pk=insight.pk).update(
            query={"kind": "HogQLQuery", "query": "select count() from persons"}
        )
        return metric

    def _other_team_metric(self, name: str) -> Metric:
        other_team = Team.objects.create_with_data(
            organization=self.organization, initiating_user=self.user, name="Other"
        )
        return Metric.objects.for_team(other_team.id).create(team=other_team, name=name, description="d")

    def test_bulk_approve_partitions_the_batch_and_reasons_every_skip(self) -> None:
        upsert_metric(team=self.team, user=self.user, name="first", description="d", definition=_HOGQL)
        upsert_metric(team=self.team, user=self.user, name="second", description="d", definition=_HOGQL)
        approve_metric(
            upsert_metric(team=self.team, user=self.user, name="blessed", description="d", definition=_HOGQL), self.user
        )
        self._drifted_metric("stale")
        soft_delete_metric(upsert_metric(team=self.team, user=self.user, name="gone", description="d"))
        theirs = self._other_team_metric("theirs")

        response = self.client.post(
            f"{self.url}bulk_approve/",
            {"names": ["first", "blessed", "stale", "gone", "theirs", "unheard_of", "second"]},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert [metric["name"] for metric in body["approved"]] == ["first", "second"]
        assert {skip["name"]: skip["reason"] for skip in body["skipped"]} == {
            "blessed": BULK_SKIP_ALREADY_APPROVED,
            "stale": BULK_SKIP_DRIFTED,
            "gone": BULK_SKIP_NOT_FOUND,
            "theirs": BULK_SKIP_NOT_FOUND,
            "unheard_of": BULK_SKIP_NOT_FOUND,
        }
        assert Metric.objects.for_team(self.team.id).get(name="stale").status == MetricStatus.PROPOSED
        theirs.refresh_from_db()
        assert theirs.status == MetricStatus.PROPOSED

    def test_bulk_approve_dedupes_repeated_names(self) -> None:
        upsert_metric(team=self.team, user=self.user, name="mrr", description="d", definition=_HOGQL)
        response = self.client.post(f"{self.url}bulk_approve/", {"names": ["mrr", "mrr"]}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert [metric["name"] for metric in response.json()["approved"]] == ["mrr"]

    def test_bulk_approve_computes_drift_in_a_single_insight_query(self) -> None:
        # Same N+1 guard as the list view: drift must not fan out into one insight lookup per metric.
        names = []
        for index in range(3):
            insight = self._insight()
            names.append(f"m{index}")
            upsert_metric(
                team=self.team,
                user=self.user,
                name=names[-1],
                description="d",
                source_insight_short_id=insight.short_id,
            )
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.post(f"{self.url}bulk_approve/", {"names": names}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.json()
        insight_queries = [q for q in ctx.captured_queries if "posthog_dashboarditem" in q["sql"]]
        assert len(insight_queries) == 1, insight_queries

    def test_bulk_approve_writes_the_audit_trail_per_metric(self) -> None:
        # The approval must go through save(), not a queryset UPDATE, or the audit trail is silently lost.
        upsert_metric(team=self.team, user=self.user, name="first", description="d", definition=_HOGQL)
        upsert_metric(team=self.team, user=self.user, name="second", description="d", definition=_HOGQL)
        ActivityLog.objects.all().delete()

        response = self.client.post(f"{self.url}bulk_approve/", {"names": ["first", "second"]}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        logged = ActivityLog.objects.filter(team_id=self.team.id, scope="Metric", activity="updated")
        assert {entry.detail["name"] for entry in logged if entry.detail} == {"first", "second"}

    def test_bulk_delete_frees_the_names_and_skips_unknown_ones(self) -> None:
        upsert_metric(team=self.team, user=self.user, name="mrr", description="d")
        upsert_metric(team=self.team, user=self.user, name="arr", description="d")
        theirs = self._other_team_metric("theirs")

        response = self.client.post(
            f"{self.url}bulk_delete/", {"names": ["mrr", "arr", "theirs", "unheard_of"]}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert body["deleted"] == ["mrr", "arr"]
        assert {skip["name"] for skip in body["skipped"]} == {"theirs", "unheard_of"}
        assert self.client.get(self.url).json()["results"] == []
        theirs.refresh_from_db()
        assert theirs.deleted is False

    @parameterized.expand(
        [
            (
                "approve_without_approval_scope",
                "bulk_approve",
                ["data_catalog:read", "data_catalog:write"],
                status.HTTP_403_FORBIDDEN,
            ),
            (
                "approve_with_approval_scope",
                "bulk_approve",
                ["data_catalog:read", "data_catalog:write", "data_catalog_approval:write"],
                status.HTTP_200_OK,
            ),
            ("delete_read_only", "bulk_delete", ["data_catalog:read"], status.HTTP_403_FORBIDDEN),
            ("delete_with_write_scope", "bulk_delete", ["data_catalog:write"], status.HTTP_200_OK),
        ]
    )
    def test_bulk_actions_enforce_token_scopes(
        self, _name: str, url_path: str, scopes: list[str], expected: int
    ) -> None:
        upsert_metric(team=self.team, user=self.user, name="mrr", description="d", definition=_HOGQL)
        self.client.logout()
        response = self.client.post(f"{self.url}{url_path}/", {"names": ["mrr"]}, format="json", **self._bearer(scopes))
        assert response.status_code == expected, response.json()

    def test_bulk_approve_rejects_an_over_cap_batch(self) -> None:
        # Wiring guard: the action validates through its request serializer. Bounds live in
        # TestMetricBulkNamesValidation.
        response = self.client.post(
            f"{self.url}bulk_approve/", {"names": [f"m{index}" for index in range(METRIC_BULK_MAX + 1)]}, format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "names"

    def test_run_reports_drift_on_approved_metric(self) -> None:
        # An approved metric whose source insight has moved on must say so in the run envelope —
        # an agent decides trust from this response alone.
        insight = Insight.objects.create(team=self.team, created_by=self.user, query=_HOGQL)
        self.client.post(
            self.url, {"name": "mrr", "description": "d", "source_insight_short_id": insight.short_id}, format="json"
        )
        assert self.client.post(f"{self.url}mrr/approve/").status_code == status.HTTP_200_OK
        Insight.objects.filter(pk=insight.pk).update(
            query={"kind": "HogQLQuery", "query": "select count() from persons"}
        )

        with patch(_PROCESS_QUERY, return_value={"results": [[1]], "hogql": "SELECT 1"}):
            response = self.client.post(f"{self.url}mrr/run/")
        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert body["status"] == MetricStatus.APPROVED
        assert body["is_drifted"] is True


class TestMetricRunThrottles(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/data_catalog/metrics/"

    def _denied(self, throttle_class: type) -> tuple:
        return (
            patch.object(throttle_class, "allow_request", return_value=False),
            patch.object(throttle_class, "wait", return_value=None),
        )

    def test_hogql_metric_uses_hogql_query_throttle(self) -> None:
        upsert_metric(team=self.team, user=self.user, name="mrr", description="d", definition=_HOGQL)
        deny, wait = self._denied(HogQLQueryThrottle)
        with deny, wait:
            response = self.client.post(f"{self.url}mrr/run/")
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS

    def test_structured_metric_uses_clickhouse_throttles(self) -> None:
        upsert_metric(
            team=self.team,
            user=self.user,
            name="purchases",
            description="d",
            definition={"kind": "EventsNode", "event": "purchase"},
        )
        deny, wait = self._denied(ClickHouseBurstRateThrottle)
        with deny, wait:
            response = self.client.post(f"{self.url}purchases/run/")
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS

    def test_markdown_metric_keeps_default_throttles(self) -> None:
        upsert_metric(
            team=self.team,
            user=self.user,
            name="activation",
            description="d",
            definition={"kind": "MarkdownDefinition", "markdown": "1. Count."},
        )
        hogql_deny, hogql_wait = self._denied(HogQLQueryThrottle)
        ch_deny, ch_wait = self._denied(ClickHouseBurstRateThrottle)
        with hogql_deny, hogql_wait, ch_deny, ch_wait:
            response = self.client.post(f"{self.url}activation/run/")
        assert response.status_code == status.HTTP_200_OK


class TestMetricRunInputValidation(SimpleTestCase):
    @parameterized.expand([("day", True), ("month", True), ("fortnight", False), ("5m", False)])
    def test_interval_choices(self, value: str, valid: bool) -> None:
        serializer = MetricRunRequestSerializer(data={"interval": value})
        assert serializer.is_valid() is valid
        if not valid:
            assert "interval" in serializer.errors

    @parameterized.expand(
        [
            ("blocking", True),
            ("async", True),
            ("lazy_async", True),
            ("force_blocking", True),
            ("force_async", True),
            ("force_cache", True),
            ("true", False),
            ("nope", False),
        ]
    )
    def test_refresh_choices(self, value: str, valid: bool) -> None:
        serializer = MetricRunQuerySerializer(data={"refresh": value})
        assert serializer.is_valid() is valid
        if not valid:
            assert "refresh" in serializer.errors

    @parameterized.expand([(0.0, True), (1.0, True), (-0.5, False), (1.5, False)])
    def test_confidence_bounds(self, value: float, valid: bool) -> None:
        serializer = MetricSerializer(data={"name": "mrr", "description": "d", "confidence": value})
        assert serializer.is_valid() is valid, serializer.errors
        if not valid:
            assert "confidence" in serializer.errors


class TestMetricBulkNamesValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("empty", 0, False),
            ("one", 1, True),
            ("at_cap", METRIC_BULK_MAX, True),
            ("over_cap", METRIC_BULK_MAX + 1, False),
        ]
    )
    def test_batch_size_bounds(self, _name: str, count: int, valid: bool) -> None:
        serializer = MetricBulkNamesRequestSerializer(data={"names": [f"m{index}" for index in range(count)]})
        assert serializer.is_valid() is valid, serializer.errors
        if not valid:
            assert "names" in serializer.errors
