import base64
from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import AsyncMock, MagicMock, patch

from parameterized import parameterized

from posthog.api.query import CONCURRENCY_LIMIT_RETRY_AFTER_SECONDS
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded, ConcurrencySlot, RateLimit
from posthog.constants import AvailableFeature
from posthog.models import Team
from posthog.models.ai_events.test_util import bulk_create_ai_events
from posthog.models.event.util import bulk_create_events
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.access_control.backend.facade.contracts import PropertyAccessLevel
from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.ai_observability.backend.models.review_queues import ReviewQueue
from products.event_definitions.backend.models.property_definition import PropertyDefinition
from products.exports.backend.facade.api import ExportedAsset

from .logic.traces.rows import make_evaluation_result_event

T0 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
GENERATION = "00000000-0000-0000-0000-000000000001"
TRACE_EVENT = "00000000-0000-0000-0000-000000000002"
EVALUATION_RESULT = "00000000-0000-0000-0000-000000000003"
QUESTION = [{"role": "user", "content": "Why did my invoice go up?"}]
ANSWER = [{"role": "assistant", "content": "Two seats were added."}]


def _create_trace(team: Team, trace_id: str = "trace-1") -> None:
    bulk_create_ai_events(
        [
            {
                "event": "$ai_generation",
                "event_uuid": "00000000-0000-0000-0000-000000000001",
                "distinct_id": "user-1",
                "team": team,
                "timestamp": T0,
                "properties": {"$ai_trace_id": trace_id, "$ai_parent_id": trace_id, "$ai_input_tokens": 3},
            }
        ]
    )


def _create_node_trace(
    team: Team,
    trace_id: str = "trace-1",
    *,
    with_trace_event: bool = True,
    extra_properties: dict[str, object] | None = None,
) -> None:
    events: list[dict[str, object]] = [
        {
            "event": "$ai_generation",
            "event_uuid": GENERATION,
            "distinct_id": "user-1",
            "team": team,
            "timestamp": T0,
            "properties": {
                "$ai_trace_id": trace_id,
                "$ai_parent_id": trace_id,
                "$ai_input": QUESTION,
                "$ai_output_choices": ANSWER,
                "$ai_tools": [{"name": "lookup_invoice"}],
                "$ai_provider": "openai",
                **(extra_properties or {}),
            },
        }
    ]
    if with_trace_event:
        events.append(
            {
                "event": "$ai_trace",
                "event_uuid": TRACE_EVENT,
                "distinct_id": "user-1",
                "team": team,
                "timestamp": T0,
                "properties": {"$ai_trace_id": trace_id, "$ai_input_state": {"question": "Why?"}},
            }
        )
    bulk_create_ai_events(events)


def _create_evaluation_result(team: Team) -> None:
    bulk_create_events(
        [
            make_evaluation_result_event(
                uuid=EVALUATION_RESULT,
                team=team,
                timestamp=T0 + timedelta(seconds=30),
                properties={
                    "$ai_target_event_id": GENERATION,
                    "$ai_evaluation_name": "Answers the question",
                    "$ai_evaluation_reasoning": "Direct answer.",
                },
            )
        ]
    )


def _encode(trace_id: str) -> str:
    return base64.urlsafe_b64encode(trace_id.encode()).decode().rstrip("=")


class TestTraceViewSet(ClickhouseTestMixin, APIBaseTest):
    def _url(self, segment: str) -> str:
        return f"/api/projects/{self.team.id}/ai_observability/traces/{segment}/"

    @parameterized.expand([("plain id", "trace-1"), ("id with a dot", "run.42"), ("id with a slash", "a/b")])
    def test_returns_the_trace_in_camel_case(self, _name: str, trace_id: str) -> None:
        _create_trace(self.team, trace_id)

        response = self.client.get(self._url(_encode(trace_id)))

        assert response.status_code == 200
        body = response.json()
        assert body["tree"][0]["id"] == trace_id
        assert body["tree"][0]["children"][0]["id"] == "00000000-0000-0000-0000-000000000001"
        assert body["totals"]["inputTokens"] == 3
        assert body["threadNodeIds"] == ["00000000-0000-0000-0000-000000000001"]
        assert body["defaultNodeId"] == "00000000-0000-0000-0000-000000000001"
        assert body["nodeIdsByAlias"] == {}

    @parameterized.expand([("unknown trace", False), ("another team's trace", True)])
    def test_not_found(self, _name: str, other_team_owns_it: bool) -> None:
        if other_team_owns_it:
            _create_trace(Team.objects.create(organization=self.organization, name="other"), "trace-2")

        assert self.client.get(self._url(_encode("trace-2"))).status_code == 404

    @parameterized.expand(
        [
            ("malformed timestamp hint", _encode("trace-1"), {"timestamp_hint": "yesterday"}),
            ("timestamp hint at the end of time", _encode("trace-1"), {"timestamp_hint": "9999-12-31T23:59:59Z"}),
            ("timestamp hint at the start of time", _encode("trace-1"), {"timestamp_hint": "0001-01-01T00:00:00Z"}),
            ("unencoded trace id", "trace-1", {}),
        ]
    )
    def test_rejects_a_malformed_request(self, _name: str, segment: str, query: dict[str, str]) -> None:
        _create_trace(self.team, "trace-1")

        assert self.client.get(self._url(segment), query).status_code == 400

    @parameterized.expand(
        [
            (f"{reader} {read}", with_api_key, exhausted_limit, suffix)
            for reader, with_api_key, exhausted_limit in [
                ("browser session", False, "app_per_org"),
                ("personal api key", True, "api_per_team"),
            ]
            for read, suffix in [
                ("trace", ""),
                ("node", f"nodes/{_encode('trace-1')}/"),
                ("evaluations", "evaluations/"),
            ]
        ]
    )
    def test_throttles_when_the_query_concurrency_limit_is_exhausted(
        self, _name: str, with_api_key: bool, exhausted_limit: str, suffix: str
    ) -> None:
        _create_trace(self.team, "trace-1")
        headers = {}
        if with_api_key:
            headers["authorization"] = f"Bearer {self.create_personal_api_key_with_scopes(['llm_analytics:read'])}"
            self.client.logout()

        def use(limiter: RateLimit, *args: object, **kwargs: object) -> ConcurrencySlot | None:
            if limiter.limit_name == exhausted_limit:
                raise ConcurrencyLimitExceeded(exhausted_limit)
            return None

        with (
            patch("posthog.clickhouse.client.limit.TEST", False),
            patch.object(RateLimit, "use", autospec=True, side_effect=use),
        ):
            response = self.client.get(self._url(_encode("trace-1")) + suffix, headers=headers)

        assert response.status_code == 429
        assert response["Retry-After"] == str(CONCURRENCY_LIMIT_RETRY_AFTER_SECONDS)


class TestTraceNodeView(ClickhouseTestMixin, APIBaseTest):
    def _url(self, trace_id: str, node_segment: str) -> str:
        return f"/api/projects/{self.team.id}/ai_observability/traces/{_encode(trace_id)}/nodes/{node_segment}/"

    def test_returns_the_properties_as_ingested_and_names_the_io_keys(self) -> None:
        _create_node_trace(self.team)

        response = self.client.get(self._url("trace-1", _encode(GENERATION)))

        assert response.status_code == 200, response.content
        body = response.json()
        assert (body["id"], body["kind"], body["error"]) == (GENERATION, "generation", None)
        assert body["metadata"]["provider"] == "openai"
        assert body["event"]["ioKeys"] == {"input": "$ai_input", "output": "$ai_output_choices", "tools": "$ai_tools"}
        assert body["event"]["properties"]["$ai_input"] == QUESTION

    @parameterized.expand([("plain id", "trace-1"), ("id with a slash", "a/b")])
    def test_root_node_is_the_trace_event(self, _name: str, trace_id: str) -> None:
        _create_node_trace(self.team, trace_id)

        body = self.client.get(self._url(trace_id, _encode(trace_id))).json()

        assert (body["id"], body["kind"]) == (trace_id, "trace")
        assert body["event"]["ioKeys"]["input"] == "$ai_input_state"

    def test_root_without_a_trace_event_has_no_event(self) -> None:
        _create_node_trace(self.team, with_trace_event=False)

        response = self.client.get(self._url("trace-1", _encode("trace-1")))

        assert response.status_code == 200
        assert response.json()["event"] is None

    @parameterized.expand(
        [
            ("unknown node", "trace-1", "00000000-0000-0000-0000-00000000ffff"),
            ("root of an unknown trace", "trace-2", "trace-2"),
            ("node of another trace", "trace-2", GENERATION),
        ]
    )
    def test_node_not_found(self, _name: str, trace_id: str, node_id: str) -> None:
        _create_node_trace(self.team)

        assert self.client.get(self._url(trace_id, _encode(node_id))).status_code == 404

    @parameterized.expand(
        [
            ("malformed trace segment", "A", _encode(GENERATION)),
            ("malformed node segment", _encode("trace-1"), "A"),
        ]
    )
    def test_rejects_a_malformed_segment(self, _name: str, trace_segment: str, node_segment: str) -> None:
        _create_node_trace(self.team)

        url = f"/api/projects/{self.team.id}/ai_observability/traces/{trace_segment}/nodes/{node_segment}/"
        assert self.client.get(url).status_code == 400

    def test_masks_properties_the_viewer_may_not_read(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.PROPERTY_ACCESS_CONTROL, "name": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        definition = PropertyDefinition.objects.create(
            team=self.team, name="secret_plan", property_type="String", type=PropertyDefinition.Type.EVENT
        )
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=definition,
            organization_member=self.organization_membership,
            access_level=PropertyAccessLevel.NONE.value,
        )
        _create_node_trace(self.team, extra_properties={"secret_plan": "enterprise"})

        properties = self.client.get(self._url("trace-1", _encode(GENERATION))).json()["event"]["properties"]

        assert "secret_plan" not in properties
        assert properties["$ai_provider"] == "openai"


class TestTraceEvaluationsView(ClickhouseTestMixin, APIBaseTest):
    def _url(self, segment: str) -> str:
        return f"/api/projects/{self.team.id}/ai_observability/traces/{segment}/evaluations/"

    def test_returns_the_results_in_camel_case(self) -> None:
        _create_evaluation_result(self.team)

        response = self.client.get(self._url(_encode("trace-1")))

        assert response.status_code == 200
        assert response.json()["results"][0] | {"timestamp": None} == {
            "id": EVALUATION_RESULT,
            "evaluationId": None,
            "evaluationName": "Answers the question",
            "targetNodeId": GENERATION,
            "outcome": "pass",
            "label": "True",
            "reasoning": "Direct answer.",
            "timestamp": None,
            "isBackfill": False,
        }

    def test_an_unknown_trace_has_no_results(self) -> None:
        response = self.client.get(self._url(_encode("trace-2")))

        assert (response.status_code, response.json()) == (200, {"results": []})

    def test_rejects_an_unencoded_trace_id(self) -> None:
        assert self.client.get(self._url("trace-1")).status_code == 400

    def test_masks_properties_the_viewer_may_not_read(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.PROPERTY_ACCESS_CONTROL, "name": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        definition = PropertyDefinition.objects.create(
            team=self.team,
            name="$ai_evaluation_reasoning",
            property_type="String",
            type=PropertyDefinition.Type.EVENT,
        )
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=definition,
            organization_member=self.organization_membership,
            access_level=PropertyAccessLevel.NONE.value,
        )
        _create_evaluation_result(self.team)

        result = self.client.get(self._url(_encode("trace-1"))).json()["results"][0]

        assert (result["reasoning"], result["outcome"]) == (None, "pass")


class TestTraceViewSetResourceLevelAccess(ClickhouseTestMixin, APIBaseTest):
    @parameterized.expand([("the trace", "get", ""), ("an export", "post", "exports/")])
    def test_a_grant_on_one_object_does_not_open_traces(self, _name: str, method: str, path: str) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        queue = ReviewQueue.objects.create(team=self.team, name="Support queue", created_by=self.user)
        member = User.objects.create_and_join(self.organization, "queue-reviewer@example.com", "testtest")
        membership = OrganizationMembership.objects.get(user=member, organization=self.organization)
        AccessControl.objects.create(
            team=self.team, resource="llm_analytics", access_level="none", organization_member=membership
        )
        AccessControl.objects.create(
            team=self.team,
            resource="llm_analytics",
            resource_id=str(queue.id),
            access_level="viewer",
            organization_member=membership,
        )
        _create_trace(self.team)
        self.client.force_login(member)

        url = f"/api/projects/{self.team.id}/ai_observability/traces/{_encode('trace-1')}/{path}"
        response = getattr(self.client, method)(url)

        assert response.status_code == 403, response.content


class TestTraceExportViews(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        async_connect = patch("products.exports.backend.facade.api.async_connect", new_callable=AsyncMock)
        self.start_workflow = async_connect.start().return_value.start_workflow
        self.addCleanup(async_connect.stop)

    def _url(self, segment: str, export_id: int | None = None, suffix: str = "") -> str:
        url = f"/api/projects/{self.team.id}/ai_observability/traces/{segment}/exports/"
        return url if export_id is None else f"{url}{export_id}/{suffix}"

    def _create(self, trace_id: str = "a/b") -> dict[str, Any]:
        response = self.client.post(self._url(_encode(trace_id)), {"timestamp_hint": T0.isoformat()}, format="json")
        assert response.status_code == 201, response.content
        return response.json()

    def test_creates_reports_and_serves_the_export_to_its_creator(self) -> None:
        export = self._create()
        export_id = export["id"]

        assert set(export) == {"id", "status", "filename", "createdAt", "expiresAfter", "exception"}
        assert (export["status"], export["exception"]) == ("pending", None)
        self.start_workflow.assert_awaited_once()
        assert self.client.get(self._url(_encode("a/b"), export_id)).json()["status"] == "pending"
        assert self.client.get(self._url(_encode("a/b"), export_id, "content/")).status_code == 409

        ExportedAsset.objects.filter(id=export_id).update(content=b'{"trace":{},"nodes":[]}')
        content = self.client.get(self._url(_encode("a/b"), export_id, "content/"))

        assert content.status_code == 200
        assert content["Content-Disposition"].startswith("attachment")
        assert self.client.get(f"/api/projects/{self.team.id}/exports/{export_id}/").status_code == 404
        self.assertRedirects(
            self.client.get(f"/api/projects/{self.team.id}/exports/{export_id}/content"),
            self._url(_encode("a/b"), export_id, "content"),
            fetch_redirect_response=False,
        )

    @parameterized.expand([("another user", True, "a/b"), ("another trace", False, "c")])
    def test_status_and_content_are_404_for(self, _name: str, as_teammate: bool, url_trace_id: str) -> None:
        export_id = self._create()["id"]
        if as_teammate:
            self.client.force_login(User.objects.create_and_join(self.organization, "peer@example.com", "testtest"))

        for suffix in ("", "content/"):
            assert self.client.get(self._url(_encode(url_trace_id), export_id, suffix)).status_code == 404

    def test_a_failed_export_reports_its_reason(self) -> None:
        export_id = self._create()["id"]
        ExportedAsset.objects.filter(id=export_id).update(
            exception="This trace is no longer available.", exception_type="InvalidExportContext"
        )

        status = self.client.get(self._url(_encode("a/b"), export_id)).json()
        content = self.client.get(self._url(_encode("a/b"), export_id, "content/"))

        assert (status["status"], status["exception"]) == ("failed", "This trace is no longer available.")
        assert (content.status_code, content.json()["detail"]) == (409, "This trace is no longer available.")

    @parameterized.expand([("a malformed hint", _encode("a/b"), "yesterday"), ("an unencoded trace id", "a+b", None)])
    def test_rejects(self, _name: str, segment: str, hint: str | None) -> None:
        response = self.client.post(self._url(segment), {"timestamp_hint": hint} if hint else {}, format="json")

        assert response.status_code == 400
        self.start_workflow.assert_not_awaited()

    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    @patch("products.ai_observability.backend.presentation.trace_exports.TraceExportRateThrottle.rate", new="1/day")
    def test_throttles_exports_per_user(self, _rate_limit: MagicMock) -> None:
        self._create()

        assert self.client.post(self._url(_encode("a/b")), {}, format="json").status_code == 429
        self.client.force_login(User.objects.create_and_join(self.organization, "peer@example.com", "testtest"))
        self._create()
