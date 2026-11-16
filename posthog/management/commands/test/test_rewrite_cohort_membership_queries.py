import json
from io import StringIO
from typing import Any

from posthog.test.base import BaseTest

from django.core.management import call_command

from parameterized import parameterized

from posthog.models import Team

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.endpoints.backend.facade.models import Endpoint, EndpointVersion
from products.notebooks.backend.models import Notebook
from products.product_analytics.backend.facade.models import Insight

MEMBERSHIP_FILTER = (
    "SELECT count() FROM events e WHERE e.person_id IN (SELECT person_id FROM cohort_membership WHERE cohort_id = 7)"
)
REWRITTEN_FILTER = MEMBERSHIP_FILTER.replace("cohort_membership", "cohort_people")
QUALIFIED = "SELECT cohort_membership.person_id FROM cohort_membership WHERE cohort_membership.cohort_id = 7"
REWRITTEN_QUALIFIED = (
    "SELECT cohort_membership.person_id FROM cohort_people AS cohort_membership WHERE cohort_membership.cohort_id = 7"
)
MEMBERSHIP_STATUS = "SELECT person_id FROM cohort_membership WHERE cohort_id = 7 AND status = 'entered'"
HOGQL_PROPERTY_FILTER = {
    "kind": "TrendsQuery",
    "series": [{"kind": "EventsNode", "event": "$pageview"}],
    "properties": [{"type": "hogql", "key": "person_id IN (SELECT person_id FROM cohort_membership)"}],
}


def _visualization(sql: str) -> dict[str, Any]:
    return {"kind": "DataVisualizationNode", "source": {"kind": "HogQLQuery", "query": sql}}


class TestRewriteCohortMembershipQueriesCommand(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.insight = Insight.objects.create(team=self.team, query=_visualization(MEMBERSHIP_FILTER))
        self.status_insight = Insight.objects.create(team=self.team, query=_visualization(MEMBERSHIP_STATUS))
        self.filter_insight = Insight.objects.create(team=self.team, query=HOGQL_PROPERTY_FILTER)
        self.view = DataWarehouseSavedQuery.objects.create(team=self.team, name="members", query={"query": QUALIFIED})
        self.view_revision = self.view.query_revision
        self.notebook = Notebook.objects.create(
            team=self.team,
            content={
                "type": "doc",
                "content": [
                    {"type": "ph-query", "attrs": {"query": _visualization(MEMBERSHIP_FILTER)}},
                    {"type": "ph-query", "attrs": {"query": json.dumps(_visualization(MEMBERSHIP_FILTER))}},
                ],
            },
        )
        endpoint = Endpoint.objects.create(team=self.team, name="members", created_by=self.user)
        self.endpoint_version = EndpointVersion.objects.create(
            endpoint=endpoint,
            team=self.team,
            version=1,
            query={"kind": "HogQLQuery", "query": MEMBERSHIP_FILTER},
            created_by=self.user,
        )
        other_team = Team.objects.create(organization=self.organization)
        self.other_team_insight = Insight.objects.create(team=other_team, query=_visualization(MEMBERSHIP_FILTER))

    def _saved_state(self) -> dict[str, Any]:
        notebook = Notebook.objects.get(pk=self.notebook.pk)
        dict_node, string_node = notebook.content["content"]
        view = DataWarehouseSavedQuery.objects.get(pk=self.view.pk)
        view_query: Any = view.query
        insight_query: Any = Insight.objects.get(pk=self.insight.pk).query
        status_query: Any = Insight.objects.get(pk=self.status_insight.pk).query
        other_team_query: Any = Insight.objects.get(pk=self.other_team_insight.pk).query
        endpoint_query: Any = EndpointVersion.objects.get(pk=self.endpoint_version.pk).query
        return {
            "insight": insight_query["source"]["query"],
            "status_insight": status_query["source"]["query"],
            "filter_insight": Insight.objects.get(pk=self.filter_insight.pk).query,
            "view": view_query["query"],
            "view_revision_rotated": view.query_revision != self.view_revision,
            "notebook_dict_node": dict_node["attrs"]["query"]["source"]["query"],
            "notebook_string_node": json.loads(string_node["attrs"]["query"])["source"]["query"],
            "notebook_version": notebook.version,
            "endpoint_version": endpoint_query["query"],
            "other_team_insight": other_team_query["source"]["query"],
        }

    @parameterized.expand(
        [
            ("dry_run", [], False),
            ("apply", ["--apply"], True),
        ]
    )
    def test_rewrites_one_teams_saved_queries_only_with_apply(self, _name: str, args: list[str], applied: bool) -> None:
        output = StringIO()

        call_command("rewrite_cohort_membership_queries", "--team-id", str(self.team.pk), *args, stdout=output)

        assert self._saved_state() == {
            "insight": REWRITTEN_FILTER if applied else MEMBERSHIP_FILTER,
            "status_insight": MEMBERSHIP_STATUS,
            "filter_insight": HOGQL_PROPERTY_FILTER,
            "view": REWRITTEN_QUALIFIED if applied else QUALIFIED,
            "view_revision_rotated": applied,
            "notebook_dict_node": REWRITTEN_FILTER if applied else MEMBERSHIP_FILTER,
            "notebook_string_node": REWRITTEN_FILTER if applied else MEMBERSHIP_FILTER,
            "notebook_version": 1 if applied else 0,
            "endpoint_version": REWRITTEN_FILTER if applied else MEMBERSHIP_FILTER,
            "other_team_insight": MEMBERSHIP_FILTER,
        }
        verb = "Rewrote" if applied else "Would rewrite"
        assert output.getvalue().splitlines()[-1] == (
            f"{verb} 4 rows. 2 rows need a manual check. 0 rows changed while running."
        )
