from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.schema import QueryStatus

from posthog.clickhouse.client.execute_async import QueryStatusManager
from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership

from products.authz.backend.facade.contracts import CheckRequest, Context
from products.authz.backend.facade.enums import ResourceType
from products.notebooks.backend.models import Notebook
from products.product_analytics.backend.facade.models import Insight

SAVED_QUERY = {
    "kind": "InsightVizNode",
    "source": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
}
CLIENT_QUERY = {"kind": "HogQLQuery", "query": "select * from persons"}


class TestGuestQuery(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ADVANCED_PERMISSIONS, "name": "Advanced permissions"}
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.GUEST
        self.organization_membership.save()
        self.insight = Insight.objects.create(team=self.team, query=SAVED_QUERY)
        self.other_insight = Insight.objects.create(team=self.team, query=SAVED_QUERY)
        notebook_content = {
            "type": "doc",
            "content": [{"type": "ph-query", "attrs": {"nodeId": "node-1", "query": SAVED_QUERY}}],
        }
        self.notebook = Notebook.objects.create(team=self.team, content=notebook_content)
        self.other_notebook = Notebook.objects.create(team=self.team, content=notebook_content)
        for target, kwargs in (
            ("products.authz.backend.logic.rollout.get_feature_flag_or_none", {"return_value": "v2"}),
            ("products.authz.backend.logic.authorization.check", {"side_effect": self._openfga_check}),
        ):
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _openfga_check(self, requests: Sequence[CheckRequest], _context: Context | None) -> list[bool]:
        return [
            request.resource.type in (ResourceType.PROJECT, ResourceType.ORGANIZATION)
            or (request.resource.type == ResourceType.INSIGHT and request.resource.id == str(self.insight.id))
            or (request.resource.type == ResourceType.NOTEBOOK and request.resource.id == str(self.notebook.id))
            or (request.resource.type == ResourceType.SESSION_RECORDING and request.resource.id == "session-1")
            for request in requests
        ]

    def _query(self, **body: Any):
        return self.client.post(f"/api/environments/{self.team.id}/query/", body, format="json")

    def test_guest_query_without_a_reference_is_denied(self) -> None:
        assert self._query(query=CLIENT_QUERY).status_code == status.HTTP_403_FORBIDDEN

    @patch("posthog.api.query.process_query_model", return_value={"results": []})
    def test_guest_query_runs_the_saved_query_not_the_client_query(self, process) -> None:
        response = self._query(query=CLIENT_QUERY, insight_id=self.insight.id)
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert process.call_args.args[1].kind == "TrendsQuery"

    def test_guest_cannot_query_an_insight_they_cannot_view(self) -> None:
        response = self._query(query=CLIENT_QUERY, insight_id=self.other_insight.id)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @parameterized.expand(
        [
            ("breakdown", {"breakdown_filter": {"breakdown": "email", "breakdown_type": "person"}}),
            ("hogql filter", {"properties": [{"type": "hogql", "key": "person.properties.email = 'a'"}]}),
        ]
    )
    def test_guest_cannot_use_overrides_that_expose_values(self, _name: str, filters_override: dict) -> None:
        response = self._query(query=CLIENT_QUERY, insight_id=self.insight.id, filters_override=filters_override)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @parameterized.expand([("granted notebook", True), ("other notebook", False)])
    @patch("posthog.api.query.process_query_model", return_value={"results": []})
    def test_guest_runs_a_notebook_node_only_in_a_granted_notebook(self, _name: str, granted: bool, process) -> None:
        notebook = self.notebook if granted else self.other_notebook
        response = self._query(query=CLIENT_QUERY, notebook_short_id=notebook.short_id, node_id="node-1")
        assert response.status_code == (status.HTTP_200_OK if granted else status.HTTP_403_FORBIDDEN)
        if granted:
            assert process.call_args.args[1].kind == "TrendsQuery"

    @patch("posthog.api.query.process_query_model", return_value={"results": []})
    def test_members_still_run_their_own_query(self, process) -> None:
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        response = self._query(query=CLIENT_QUERY, insight_id=self.insight.id)
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert process.call_args.args[1].kind == "HogQLQuery"

    @parameterized.expand([("own query", True), ("another user's query", False)])
    def test_guest_reads_and_cancels_only_their_own_async_query(self, _name: str, own: bool) -> None:
        user_id = self.user.pk if own else self.user.pk + 1
        QueryStatusManager("query-1", self.team.pk).store_query_status(
            QueryStatus(id="query-1", team_id=self.team.pk, user_id=user_id, complete=True, results=[1])
        )
        status_response = self.client.get(f"/api/environments/{self.team.id}/query/query-1/")
        assert (status_response.status_code == status.HTTP_404_NOT_FOUND) is not own, status_response.json()
        if not own:
            cancel = self.client.delete(f"/api/environments/{self.team.id}/query/query-1/")
            assert cancel.status_code == status.HTTP_404_NOT_FOUND

    @parameterized.expand([("granted recording", "session-1"), ("other recording", "session-2")])
    @patch("posthog.api.query.process_query_model", return_value={"results": []})
    def test_guest_loads_events_only_for_a_granted_recording(self, _name: str, session_id: str, process) -> None:
        metadata = {"start_time": datetime(2026, 1, 1, tzinfo=UTC), "end_time": datetime(2026, 1, 1, 1, tzinfo=UTC)}
        with patch("posthog.api.services.guest_query.SessionReplayEvents.get_metadata", return_value=metadata):
            response = self._query(query=CLIENT_QUERY, session_recording_id=session_id)
        granted = session_id == "session-1"
        assert response.status_code == (status.HTTP_200_OK if granted else status.HTTP_403_FORBIDDEN)
        if granted:
            query = process.call_args.args[1]
            assert query.kind == "HogQLQuery"
            assert "$session_id = {session_id}" in query.query
            assert query.values["session_id"] == "session-1"
