import json
from io import StringIO
from typing import Any

from posthog.test.base import BaseTest

from django.core.management import call_command

from parameterized import parameterized

from posthog.models import Team
from posthog.models.cohortmembership.query_rewrite import rewrite_query_nodes, rewrite_saved_rows
from posthog.redis import get_client

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery, Edge
from products.endpoints.backend.facade.models import Endpoint, EndpointVersion
from products.notebooks.backend.collab_stream import STREAM_KEY_PATTERN
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


def _markdown_with_query(sql: str) -> str:
    return "# Members\n\n<Query query={" + json.dumps(_visualization(sql)) + "} />\n"


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
        self.markdown_notebook = Notebook.objects.create(
            team=self.team,
            content={
                "type": "doc",
                "content": [
                    {"type": "ph-markdown-notebook", "attrs": {"markdown": _markdown_with_query(MEMBERSHIP_FILTER)}}
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
        stream_key = STREAM_KEY_PATTERN.format(team_id=self.team.pk, notebook_id=notebook.short_id)
        last_stream_entry = get_client().xrevrange(stream_key, count=1)
        markdown_content: Any = Notebook.objects.get(pk=self.markdown_notebook.pk).content
        return {
            "insight": insight_query["source"]["query"],
            "status_insight": status_query["source"]["query"],
            "filter_insight": Insight.objects.get(pk=self.filter_insight.pk).query,
            "view": view_query["query"],
            "view_revision_rotated": view.query_revision != self.view_revision,
            "view_parents": sorted(edge.source.name for edge in Edge.objects.filter(target__saved_query=view)),
            "notebook_dict_node": dict_node["attrs"]["query"]["source"]["query"],
            "notebook_string_node": json.loads(string_node["attrs"]["query"])["source"]["query"],
            "notebook_version": notebook.version,
            "markdown_notebook": markdown_content["content"][0]["attrs"]["markdown"],
            "notebook_stream_entry": last_stream_entry[0][0].decode() if last_stream_entry else None,
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
            "view_parents": ["cohort_people"] if applied else [],
            "notebook_dict_node": REWRITTEN_FILTER if applied else MEMBERSHIP_FILTER,
            "notebook_string_node": REWRITTEN_FILTER if applied else MEMBERSHIP_FILTER,
            "notebook_version": 1 if applied else 0,
            "markdown_notebook": _markdown_with_query(REWRITTEN_FILTER if applied else MEMBERSHIP_FILTER),
            "notebook_stream_entry": "1-1" if applied else None,
            "endpoint_version": REWRITTEN_FILTER if applied else MEMBERSHIP_FILTER,
            "other_team_insight": MEMBERSHIP_FILTER,
        }
        lines = output.getvalue().splitlines()
        assert lines[lines.index(f"insight {self.status_insight.pk} (team {self.team.pk}):") + 1] == (
            "  a query needs a manual fix"
        )
        assert lines[lines.index(f"insight {self.filter_insight.pk} (team {self.team.pk}):") + 1] == (
            "  still names cohort_membership outside a query this command rewrites"
        )
        verb = "Rewrote" if applied else "Would rewrite"
        assert lines[-1] == f"{verb} 5 rows. 2 rows need a manual check. 0 rows changed while running."

    def test_skips_a_row_edited_after_the_read(self) -> None:
        edited = _visualization(MEMBERSHIP_STATUS)

        def rewrite_after_an_edit(value: Any) -> tuple[Any, list[Any]]:
            Insight.objects.filter(pk=self.insight.pk).update(query=edited)
            return rewrite_query_nodes(value)

        [row] = rewrite_saved_rows(
            Insight.objects.filter(pk=self.insight.pk), "query", "insight", rewrite_after_an_edit, apply=True
        )

        assert (row.changed, row.written) == (True, False)
        assert Insight.objects.get(pk=self.insight.pk).query == edited
