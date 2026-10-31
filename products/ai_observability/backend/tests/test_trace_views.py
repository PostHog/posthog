import base64
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import ANY, AsyncMock, MagicMock, patch

from parameterized import parameterized

from posthog.api.query import CONCURRENCY_LIMIT_RETRY_AFTER_SECONDS
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded, ConcurrencySlot, RateLimit
from posthog.constants import AvailableFeature
from posthog.exceptions import ClickHouseQueryTimeOut
from posthog.models import Team
from posthog.models.ai_events.test_util import bulk_create_ai_events
from posthog.models.event.util import bulk_create_events
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.access_control.backend.facade.contracts import PropertyAccessLevel
from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.ai_observability.backend.logic.traces import trace_queries
from products.ai_observability.backend.logic.traces.summary import ReadySummary, SummaryItem
from products.ai_observability.backend.logic.traces.summary_store import summary_key, write_summary
from products.ai_observability.backend.models.review_queues import ReviewQueue
from products.engineering_analytics.backend.facade import api as engineering_analytics_api
from products.engineering_analytics.backend.facade.contracts import ENGINEERING_ANALYTICS_FEATURE_FLAG, BranchPRMatch
from products.event_definitions.backend.models.property_definition import PropertyDefinition
from products.exports.backend.facade.api import ExportedAsset

from .logic.traces.rows import make_cluster, make_cluster_run_event, make_evaluation_result_event

if TYPE_CHECKING:
    from rest_framework.response import _MonkeyPatchedResponse

T0 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
GENERATION = "00000000-0000-0000-0000-000000000001"
TRACE_EVENT = "00000000-0000-0000-0000-000000000002"
EVALUATION_RESULT = "00000000-0000-0000-0000-000000000003"
SCORE = "00000000-0000-0000-0000-000000000004"
FEEDBACK = "00000000-0000-0000-0000-000000000005"
QUESTION = [{"role": "user", "content": "Why did my invoice go up?"}]
ANSWER = [{"role": "assistant", "content": "Two seats were added."}]


def _create_trace(team: Team, trace_id: str = "trace-1", *, extra_properties: dict[str, object] | None = None) -> None:
    bulk_create_ai_events(
        [
            {
                "event": "$ai_generation",
                "event_uuid": "00000000-0000-0000-0000-000000000001",
                "distinct_id": "user-1",
                "team": team,
                "timestamp": T0,
                "properties": {
                    "$ai_trace_id": trace_id,
                    "$ai_parent_id": trace_id,
                    "$ai_input_tokens": 3,
                    **(extra_properties or {}),
                },
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


def _restrict_property(test: APIBaseTest, name: str) -> None:
    test.organization.available_product_features = [
        {"key": AvailableFeature.PROPERTY_ACCESS_CONTROL, "name": AvailableFeature.PROPERTY_ACCESS_CONTROL}
    ]
    test.organization.save()
    definition = PropertyDefinition.objects.create(
        team=test.team, name=name, property_type="String", type=PropertyDefinition.Type.EVENT
    )
    PropertyAccessControl.objects.create(
        team=test.team,
        property_definition=definition,
        organization_member=test.organization_membership,
        access_level=PropertyAccessLevel.NONE.value,
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

    @parameterized.expand(
        [
            ("visible", False, {"branch": "feat/rag", "repo": "acme/app"}),
            ("restricted for the viewer", True, None),
        ]
    )
    def test_returns_the_git_branch_unless_the_viewer_may_not_read_it(
        self, _name: str, restricted: bool, expected: dict[str, str] | None
    ) -> None:
        if restricted:
            _restrict_property(self, "$ai_git_branch")
        _create_trace(self.team, extra_properties={"$ai_git_branch": "feat/rag", "$ai_git_repo": "acme/app"})

        assert self.client.get(self._url(_encode("trace-1"))).json()["git"] == expected

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
                ("clusters", "clusters/?created_at=2026-09-01T10:00:00Z"),
                ("search", "search/?q=invoice"),
            ]
        ]
    )
    def test_throttles_when_the_query_concurrency_limit_is_exhausted(
        self, _name: str, with_api_key: bool, exhausted_limit: str, suffix: str
    ) -> None:
        _create_trace(self.team, "trace-1")
        headers = {}
        if with_api_key:
            key = self.create_personal_api_key_with_scopes(["llm_analytics:read", "ai_observability_clusters:read"])
            headers["authorization"] = f"Bearer {key}"
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
        _restrict_property(self, "secret_plan")
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
        body = response.json()
        assert body["results"][0] | {"timestamp": None} == {
            "id": EVALUATION_RESULT,
            "evaluationId": None,
            "evaluationName": "Answers the question",
            "targetNodeId": GENERATION,
            "outcome": "pass",
            "label": "True",
            "score": None,
            "reasoning": "Direct answer.",
            "timestamp": None,
            "isBackfill": False,
        }
        assert body["summary"] == {
            "passed": 1,
            "failed": 0,
            "unrated": 0,
            "nodes": [{"nodeId": GENERATION, "outcome": "pass"}],
        }

    def test_an_unknown_trace_has_no_results(self) -> None:
        response = self.client.get(self._url(_encode("trace-2")))

        assert (response.status_code, response.json()) == (
            200,
            {"results": [], "summary": {"passed": 0, "failed": 0, "unrated": 0, "nodes": []}},
        )

    def test_rejects_an_unencoded_trace_id(self) -> None:
        assert self.client.get(self._url("trace-1")).status_code == 400

    def test_masks_properties_the_viewer_may_not_read(self) -> None:
        _restrict_property(self, "$ai_evaluation_reasoning")
        _create_evaluation_result(self.team)

        result = self.client.get(self._url(_encode("trace-1"))).json()["results"][0]

        assert (result["reasoning"], result["outcome"]) == (None, "pass")


class TestTraceClustersView(ClickhouseTestMixin, APIBaseTest):
    def _url(self, segment: str) -> str:
        return f"/api/projects/{self.team.id}/ai_observability/traces/{segment}/clusters/"

    def _create_cluster_run(self) -> None:
        bulk_create_events(
            [
                make_cluster_run_event(
                    uuid="00000000-0000-0000-0000-0000000c4001",
                    team=self.team,
                    timestamp=T0 + timedelta(days=1),
                    clusters=[
                        make_cluster(3, ["trace-1"], title="Billing questions", description="Users ask about invoices.")
                    ],
                )
            ]
        )

    def test_returns_the_clusters_in_camel_case(self) -> None:
        self._create_cluster_run()

        response = self.client.get(self._url(_encode("trace-1")), {"created_at": T0.isoformat()})

        assert response.status_code == 200
        assert response.json()["clusters"][0] | {"runAt": None} == {
            "runId": "1_trace_20260902_030000",
            "runAt": None,
            "jobId": None,
            "jobName": None,
            "clusterId": 3,
            "title": "Billing questions",
            "description": "Users ask about invoices.",
            "isOutlier": False,
        }

    @parameterized.expand(
        [
            ("an unencoded id", "trace-1", {"created_at": "2026-09-01T10:00:00Z"}),
            ("no created_at", _encode("trace-1"), {}),
            ("a malformed created_at", _encode("trace-1"), {"created_at": "yesterday"}),
            ("an out-of-range created_at", _encode("trace-1"), {"created_at": "9999-12-31T00:00:00Z"}),
        ]
    )
    def test_rejects_a_malformed_request(self, _name: str, segment: str, query: dict[str, str]) -> None:
        assert self.client.get(self._url(segment), query).status_code == 400

    def test_an_api_key_needs_the_clusters_scope(self) -> None:
        key = self.create_personal_api_key_with_scopes(["llm_analytics:read"])
        self.client.logout()

        response = self.client.get(
            self._url(_encode("trace-1")), {"created_at": T0.isoformat()}, headers={"authorization": f"Bearer {key}"}
        )

        assert response.status_code == 403

    def test_masks_clusters_the_viewer_may_not_read(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.PROPERTY_ACCESS_CONTROL, "name": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        definition = PropertyDefinition.objects.create(
            team=self.team, name="$ai_clusters", property_type="String", type=PropertyDefinition.Type.EVENT
        )
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=definition,
            organization_member=self.organization_membership,
            access_level=PropertyAccessLevel.NONE.value,
        )
        self._create_cluster_run()

        response = self.client.get(self._url(_encode("trace-1")), {"created_at": T0.isoformat()})

        assert (response.status_code, response.json()) == (200, {"clusters": []})


def _create_feedback(team: Team) -> None:
    def event(uuid: str, name: str, properties: dict[str, object]) -> dict[str, object]:
        return {
            "event": name,
            "event_uuid": uuid,
            "distinct_id": "user-1",
            "team": team,
            "timestamp": T0 + timedelta(minutes=1),
            "properties": {"$ai_trace_id": "trace-1", **properties},
        }

    _create_trace(team)
    bulk_create_ai_events(
        [
            event(
                SCORE,
                "$ai_metric",
                {"$ai_metric_name": "helpfulness", "$ai_metric_value": 0, "$ai_parent_id": GENERATION},
            ),
            event(FEEDBACK, "$ai_feedback", {"$ai_feedback_text": "Too long, but correct."}),
        ]
    )


class TestTraceFeedbackView(ClickhouseTestMixin, APIBaseTest):
    def _url(self, segment: str) -> str:
        return f"/api/projects/{self.team.id}/ai_observability/traces/{segment}/feedback/"

    def test_returns_the_feedback_in_camel_case(self) -> None:
        _create_feedback(self.team)

        response = self.client.get(self._url(_encode("trace-1")))

        assert response.status_code == 200
        body = response.json()
        assert [score | {"timestamp": None} for score in body["scores"]] == [
            {"id": SCORE, "name": "helpfulness", "value": "0", "nodeId": GENERATION, "timestamp": None}
        ]
        assert [(item["kind"], item["text"], item["nodeId"]) for item in body["responses"]] == [
            ("text", "Too long, but correct.", "trace-1")
        ]
        assert body["summary"]["total"] == 2
        assert body["surveyResponsesStatus"] == "ok"

    @parameterized.expand(
        [
            ("only the trace scope", ["llm_analytics:read"], "not_permitted"),
            ("the survey response scopes too", ["llm_analytics:read", "survey:read", "query:read"], "ok"),
        ]
    )
    def test_includes_survey_responses_only_for_a_token_with_the_survey_scopes(
        self, _name: str, scopes: list[str], expected: str
    ) -> None:
        _create_feedback(self.team)
        headers = {"authorization": f"Bearer {self.create_personal_api_key_with_scopes(scopes)}"}
        self.client.logout()

        response = self.client.get(self._url(_encode("trace-1")), headers=headers)

        assert response.status_code == 200
        assert (response.json()["surveyResponsesStatus"], response.json()["summary"]["total"]) == (expected, 2)

    def test_an_unknown_trace_has_no_feedback(self) -> None:
        response = self.client.get(self._url(_encode("trace-2")))

        assert response.status_code == 200
        assert (response.json()["scores"], response.json()["responses"], response.json()["summary"]["total"]) == (
            [],
            [],
            0,
        )

    def test_rejects_an_unencoded_trace_id(self) -> None:
        assert self.client.get(self._url("trace-1")).status_code == 400

    def test_masks_feedback_the_viewer_may_not_read(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.PROPERTY_ACCESS_CONTROL, "name": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        definition = PropertyDefinition.objects.create(
            team=self.team, name="$ai_feedback_text", property_type="String", type=PropertyDefinition.Type.EVENT
        )
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=definition,
            organization_member=self.organization_membership,
            access_level=PropertyAccessLevel.NONE.value,
        )
        _create_feedback(self.team)

        body = self.client.get(self._url(_encode("trace-1"))).json()

        assert (len(body["scores"]), body["responses"]) == (1, [])


class TestTraceSearchView(ClickhouseTestMixin, APIBaseTest):
    def _url(self, trace_id: str) -> str:
        return f"/api/projects/{self.team.id}/ai_observability/traces/{_encode(trace_id)}/search/"

    def test_returns_matches_in_camel_case(self) -> None:
        _create_node_trace(self.team)

        response = self.client.get(self._url("trace-1"), {"q": "Invoice"})

        assert response.status_code == 200, response.content
        assert response.json() == {"total": 2, "matches": [{"nodeId": GENERATION, "count": 2}]}

    @parameterized.expand([("no query", {}), ("a blank query", {"q": "  "}), ("a long query", {"q": "a" * 201})])
    def test_rejects_a_bad_query(self, _name: str, query: dict[str, str]) -> None:
        _create_node_trace(self.team)

        assert self.client.get(self._url("trace-1"), query).status_code == 400

    def test_unknown_trace_is_not_found(self) -> None:
        assert self.client.get(self._url("trace-2"), {"q": "invoice"}).status_code == 404

    def test_restricted_content_never_matches(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.PROPERTY_ACCESS_CONTROL, "name": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        definition = PropertyDefinition.objects.create(
            team=self.team, name="$ai_input", property_type="String", type=PropertyDefinition.Type.EVENT
        )
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=definition,
            organization_member=self.organization_membership,
            access_level=PropertyAccessLevel.NONE.value,
        )
        _create_node_trace(self.team)

        assert self.client.get(self._url("trace-1"), {"q": "go up"}).json() == {"total": 0, "matches": []}

    def test_the_search_time_limit_reaches_clickhouse_and_a_timeout_is_a_504(self) -> None:
        with patch.object(trace_queries, "query_ai_events", side_effect=ClickHouseQueryTimeOut()) as query:
            assert self.client.get(self._url("trace-1"), {"q": "invoice"}).status_code == 504

        assert query.call_args.kwargs["settings"].max_execution_time == 10


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


READY_SUMMARY = ReadySummary(
    title="Refund request",
    bullets=(SummaryItem(text="The user asks for a refund.", node_id=GENERATION),),
    notes=(),
    flow="ask → refuse",
    model="gpt-4.1-mini",
    generated_at=T0,
)


class TestTraceSummaryViews(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        self.start = self.enterContext(
            patch("products.ai_observability.backend.facade.api.start_trace_summary", return_value=None)
        )

    def _url(self, segment: str = _encode("trace-1")) -> str:
        return f"/api/projects/{self.team.id}/ai_observability/traces/{segment}/summary/"

    def _store_ready(self) -> None:
        write_summary(summary_key(self.team, self.user, "trace-1"), READY_SUMMARY)

    @parameterized.expand(
        [
            ("no summary", "none", _encode("trace-1"), 404),
            ("a ready summary", "ready", _encode("trace-1"), 200),
            ("an organization without approval", "unapproved", _encode("trace-1"), 403),
            ("a malformed id", "ready", "A", 400),
        ]
    )
    def test_get_maps_each_outcome(self, _name: str, setup: str, segment: str, expected_status: int) -> None:
        if setup != "none":
            self._store_ready()
        if setup == "unapproved":
            self.organization.is_ai_data_processing_approved = False
            self.organization.save()

        response = self.client.get(self._url(segment))

        assert response.status_code == expected_status
        if expected_status == 200:
            body = response.json()
            assert body["status"] == "ready" and body["content"]["generatedAt"] is not None
            assert body["content"]["bullets"][0]["nodeId"] == GENERATION

    def test_post_returns_202_while_pending_and_200_for_a_ready_summary(self) -> None:
        pending = self.client.post(f"{self._url()}?{urlencode({'timestamp_hint': T0.isoformat()})}", {}, format="json")
        self.start.assert_called_once()
        write_summary(summary_key(self.team, self.user, "trace-1"), READY_SUMMARY)
        ready = self.client.post(self._url(), {}, format="json")

        assert (pending.status_code, pending.json()["status"]) == (202, "pending")
        assert self.start.call_args.args[0].timestamp_hint == T0
        assert (ready.status_code, ready.json()["status"]) == (200, "ready")

    @parameterized.expand(
        [
            ("a read key reads", "llm_analytics:read", "get", 200),
            ("a read key cannot request", "llm_analytics:read", "post", 403),
            ("a write key requests", "llm_analytics:write", "post", 200),
        ]
    )
    def test_scopes(self, _name: str, scope: str, method: str, expected_status: int) -> None:
        self._store_ready()
        key = self.create_personal_api_key_with_scopes([scope])
        self.client.logout()

        send = self.client.get if method == "get" else self.client.post
        response = send(self._url(), headers={"authorization": f"Bearer {key}"})

        assert response.status_code == expected_status

    @patch("posthog.rate_limit.AIObservabilitySummarizationBurstThrottle.rate", new="1/minute")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_only_requests_are_throttled(self, _rate_limit_enabled: object) -> None:
        self._store_ready()

        assert self.client.post(self._url(), {}, format="json").status_code == 200
        assert self.client.post(self._url(), {}, format="json").status_code == 429
        assert self.client.get(self._url()).status_code == 200


PULL_REQUEST_MATCH = BranchPRMatch(repo="acme/app", number=42, title="Answer billing questions", state="open")


class TestTracePullRequestView(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        _create_trace(self.team, extra_properties={"$ai_git_branch": "feat/rag", "$ai_git_repo": "acme/app"})

    def _get(
        self, segment: str = _encode("trace-1"), *, flag: bool = True, headers: dict[str, str] | None = None
    ) -> tuple["_MonkeyPatchedResponse", MagicMock]:
        def only_engineering_analytics(key: str, *args: object, **kwargs: object) -> bool:
            return flag and key == ENGINEERING_ANALYTICS_FEATURE_FLAG

        with (
            patch("posthoganalytics.feature_enabled", side_effect=only_engineering_analytics),
            patch.object(engineering_analytics_api, "resolve_branch", return_value=[PULL_REQUEST_MATCH]) as resolve,
        ):
            response = self.client.get(
                f"/api/projects/{self.team.id}/ai_observability/traces/{segment}/pull_request/",
                {"timestamp_hint": T0.isoformat()},
                headers=headers or {},
            )
        return response, resolve

    def test_returns_the_pull_request_in_camel_case(self) -> None:
        response, _resolve = self._get()

        assert (response.status_code, response.json()) == (
            200,
            {
                "pullRequest": {
                    "repoOwner": "acme",
                    "repoName": "app",
                    "number": 42,
                    "title": "Answer billing questions",
                }
            },
        )

    def test_requires_the_engineering_analytics_flag(self) -> None:
        response, resolve = self._get(flag=False)

        assert (response.status_code, resolve.called) == (403, False)

    @parameterized.expand([(["llm_analytics:read"], 403), (["llm_analytics:read", "engineering_analytics:read"], 200)])
    def test_an_api_key_needs_both_scopes(self, scopes: list[str], expected_status: int) -> None:
        key = self.create_personal_api_key_with_scopes(scopes)
        self.client.logout()

        response, _resolve = self._get(headers={"authorization": f"Bearer {key}"})

        assert response.status_code == expected_status, response.content

    def test_rejects_an_unencoded_trace_id(self) -> None:
        response, resolve = self._get("trace-1")

        assert (response.status_code, resolve.called) == (400, False)


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

    def test_an_export_whose_workflow_never_started_fails_at_once(self) -> None:
        self.start_workflow.side_effect = RuntimeError("Temporal is unreachable")

        export = self._create()
        status = self.client.get(self._url(_encode("a/b"), export["id"])).json()

        expected = ("failed", "The export could not be started. Try again.")
        assert (export["status"], export["exception"]) == expected
        assert (status["status"], status["exception"]) == expected

    @patch("products.ai_observability.backend.presentation.views.report_user_action")
    def test_tracks_a_download(self, report_user_action: MagicMock) -> None:
        export_id = self._create()["id"]
        ExportedAsset.objects.filter(id=export_id).update(content=b'{"trace":{},"nodes":[]}')

        with self.captureOnCommitCallbacks(execute=True):
            self.client.get(self._url(_encode("a/b"), export_id, "content/"))

        report_user_action.assert_called_once_with(
            self.user, "llma trace export downloaded", {"export_id": export_id}, team=self.team, request=ANY
        )

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
