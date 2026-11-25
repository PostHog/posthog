from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.exceptions import ClickHouseQueryTimeOut

from products.access_control.backend.facade.contracts import PropertyAccessLevel
from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.ai_observability.backend.logic.traces import trace_queries
from products.event_definitions.backend.models.property_definition import PropertyDefinition

from .trace_fixtures import GENERATION, create_node_trace, encode_segment


class TestTraceSearchView(ClickhouseTestMixin, APIBaseTest):
    def _url(self, trace_id: str) -> str:
        return f"/api/projects/{self.team.id}/ai_observability/traces/{encode_segment(trace_id)}/search/"

    def test_returns_matches_in_camel_case(self) -> None:
        create_node_trace(self.team)

        response = self.client.get(self._url("trace-1"), {"q": "Invoice"})

        assert response.status_code == 200, response.content
        assert response.json() == {"total": 2, "matches": [{"nodeId": GENERATION, "count": 2}]}

    @parameterized.expand([("no query", {}), ("a blank query", {"q": "  "}), ("a long query", {"q": "a" * 201})])
    def test_rejects_a_bad_query(self, _name: str, query: dict[str, str]) -> None:
        create_node_trace(self.team)

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
        create_node_trace(self.team)

        assert self.client.get(self._url("trace-1"), {"q": "go up"}).json() == {"total": 0, "matches": []}

    def test_the_search_time_limit_reaches_clickhouse_and_a_timeout_is_a_504(self) -> None:
        with patch.object(trace_queries, "query_ai_events", side_effect=ClickHouseQueryTimeOut()) as query:
            assert self.client.get(self._url("trace-1"), {"q": "invoice"}).status_code == 504

        assert query.call_args.kwargs["settings"].max_execution_time == 10
