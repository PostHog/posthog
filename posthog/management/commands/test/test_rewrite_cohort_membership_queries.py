from io import StringIO
from typing import Any, Optional

from posthog.test.base import BaseTest

from django.core.management import call_command
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.management.commands.rewrite_cohort_membership_queries import rewrite_hogql

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.endpoints.backend.facade.models import Endpoint, EndpointVersion
from products.notebooks.backend.models import Notebook
from products.product_analytics.backend.facade.models import Insight

MEMBERSHIP_FILTER = (
    "SELECT count() FROM events e WHERE e.person_id IN (SELECT person_id FROM cohort_membership WHERE cohort_id = 7)"
)
REWRITTEN_FILTER = MEMBERSHIP_FILTER.replace("cohort_membership", "cohort_people")
MEMBERSHIP_STATUS = "SELECT person_id FROM cohort_membership WHERE cohort_id = 7 AND status = 'entered'"
HOGQL_PROPERTY_FILTER = {
    "kind": "TrendsQuery",
    "series": [{"kind": "EventsNode", "event": "$pageview"}],
    "properties": [{"type": "hogql", "key": "person_id IN (SELECT person_id FROM cohort_membership)"}],
}


class TestRewriteHogQL(SimpleTestCase):
    @parameterized.expand(
        [
            ("subquery_filter", MEMBERSHIP_FILTER, True, REWRITTEN_FILTER),
            (
                "aliased_join",
                "SELECT count() FROM events e JOIN cohort_membership AS cm ON cm.person_id = e.person_id",
                True,
                "SELECT count() FROM events e JOIN cohort_people AS cm ON cm.person_id = e.person_id",
            ),
            (
                "qualified_by_table_name",
                "SELECT cohort_membership.person_id FROM cohort_membership WHERE cohort_membership.cohort_id = 7",
                True,
                "SELECT cohort_membership.person_id FROM cohort_people AS cohort_membership WHERE cohort_membership.cohort_id = 7",
            ),
            (
                "posthog_namespace",
                "SELECT person_id FROM posthog.cohort_membership WHERE cohort_id = 7",
                True,
                "SELECT person_id FROM cohort_people WHERE cohort_id = 7",
            ),
            (
                "outer_select_star_is_another_scope",
                "SELECT * FROM events WHERE person_id IN (SELECT person_id FROM cohort_membership WHERE cohort_id = 7)",
                True,
                "SELECT * FROM events WHERE person_id IN (SELECT person_id FROM cohort_people WHERE cohort_id = 7)",
            ),
            ("reads_status", MEMBERSHIP_STATUS, True, None),
            ("reads_aliased_last_updated", "SELECT max(cm.last_updated) FROM cohort_membership cm", True, None),
            ("select_star", "SELECT * FROM cohort_membership", True, None),
            ("unparseable", "SELECT FROM cohort_membership WHERE", True, None),
            (
                "column_or_text_only",
                "SELECT 'cohort_membership' AS name, cohort_membership_changed FROM events",
                False,
                None,
            ),
            (
                "cte_with_the_same_name",
                "WITH cohort_membership AS (SELECT person_id FROM cohort_people) SELECT person_id FROM cohort_membership",
                False,
                None,
            ),
            (
                "cte_shadows_only_its_own_query",
                "SELECT count() FROM events WHERE person_id IN (SELECT person_id FROM cohort_membership WHERE cohort_id = 7)"
                " AND person_id IN (WITH cohort_membership AS (SELECT 1 AS person_id) SELECT person_id FROM cohort_membership)",
                True,
                "SELECT count() FROM events WHERE person_id IN (SELECT person_id FROM cohort_people WHERE cohort_id = 7)"
                " AND person_id IN (WITH cohort_membership AS (SELECT 1 AS person_id) SELECT person_id FROM cohort_membership)",
            ),
        ]
    )
    def test_rewrite_hogql(self, _name: str, sql: str, reads_table: bool, expected_after: Optional[str]) -> None:
        rewrite = rewrite_hogql(sql)
        assert (rewrite is not None) is reads_table
        assert (rewrite.after if rewrite else None) == expected_after


def _visualization(sql: str) -> dict[str, Any]:
    return {"kind": "DataVisualizationNode", "source": {"kind": "HogQLQuery", "query": sql}}


class TestRewriteCohortMembershipQueriesCommand(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.insight = Insight.objects.create(team=self.team, query=_visualization(MEMBERSHIP_FILTER))
        self.status_insight = Insight.objects.create(team=self.team, query=_visualization(MEMBERSHIP_STATUS))
        self.filter_insight = Insight.objects.create(team=self.team, query=HOGQL_PROPERTY_FILTER)
        self.view = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="internal_users", query={"query": MEMBERSHIP_FILTER}
        )
        self.notebook = Notebook.objects.create(
            team=self.team,
            content={
                "type": "doc",
                "content": [{"type": "ph-query", "attrs": {"query": _visualization(MEMBERSHIP_FILTER)}}],
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

    def _saved_sql(self) -> list[Any]:
        insight_queries: list[Any] = [
            Insight.objects.get(pk=pk).query for pk in (self.insight.pk, self.status_insight.pk)
        ]
        view_query: Any = DataWarehouseSavedQuery.objects.get(pk=self.view.pk).query
        notebook_content: Any = Notebook.objects.get(pk=self.notebook.pk).content
        return [
            *(query["source"]["query"] for query in insight_queries),
            view_query["query"],
            notebook_content["content"][0]["attrs"]["query"]["source"]["query"],
            EndpointVersion.objects.get(pk=self.endpoint_version.pk).query["query"],
            Insight.objects.get(pk=self.filter_insight.pk).query,
            Notebook.objects.get(pk=self.notebook.pk).version,
        ]

    @parameterized.expand(
        [
            ("dry_run", [], MEMBERSHIP_FILTER, 0, "Would rewrite 4 rows. 2 rows need a manual check."),
            ("apply", ["--apply"], REWRITTEN_FILTER, 1, "Rewrote 4 rows. 2 rows need a manual check."),
        ]
    )
    def test_rewrites_saved_queries_only_with_apply(
        self, _name: str, args: list[str], expected_sql: str, notebook_version: int, summary: str
    ) -> None:
        output = StringIO()

        call_command("rewrite_cohort_membership_queries", *args, stdout=output)

        assert self._saved_sql() == [
            expected_sql,
            MEMBERSHIP_STATUS,
            expected_sql,
            expected_sql,
            expected_sql,
            HOGQL_PROPERTY_FILTER,
            notebook_version,
        ]
        assert output.getvalue().splitlines()[-1] == summary
