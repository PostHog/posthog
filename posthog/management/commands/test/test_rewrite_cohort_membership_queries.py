from io import StringIO
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command

from parameterized import parameterized

from posthog.models import Team
from posthog.models.cohortmembership import query_rewrite
from posthog.models.cohortmembership.query_rewrite import rewrite_saved_rows

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


def _visualization(sql: str) -> dict[str, Any]:
    return {"kind": "DataVisualizationNode", "source": {"kind": "HogQLQuery", "query": sql}}


class TestRewriteCohortMembershipQueriesCommand(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.insight = Insight.objects.create(team=self.team, query=_visualization(MEMBERSHIP_FILTER))
        self.status_insight = Insight.objects.create(team=self.team, query=_visualization(MEMBERSHIP_STATUS))
        self.filter_insight = Insight.objects.create(team=self.team, query=HOGQL_PROPERTY_FILTER)
        other_team = Team.objects.create(organization=self.organization)
        self.other_team_insight = Insight.objects.create(team=other_team, query=_visualization(MEMBERSHIP_FILTER))

    def _saved_queries(self) -> dict[str, Any]:
        insights = {
            "insight": self.insight,
            "status_insight": self.status_insight,
            "filter_insight": self.filter_insight,
            "other_team_insight": self.other_team_insight,
        }
        return {name: Insight.objects.get(pk=insight.pk).query for name, insight in insights.items()}

    @parameterized.expand(
        [
            ("dry_run", [], False),
            ("apply", ["--apply"], True),
        ]
    )
    def test_rewrites_one_teams_insights_only_with_apply(self, _name: str, args: list[str], applied: bool) -> None:
        output = StringIO()

        call_command("rewrite_cohort_membership_queries", "--team-id", str(self.team.pk), *args, stdout=output)

        assert self._saved_queries() == {
            "insight": _visualization(REWRITTEN_FILTER if applied else MEMBERSHIP_FILTER),
            "status_insight": _visualization(MEMBERSHIP_STATUS),
            "filter_insight": HOGQL_PROPERTY_FILTER,
            "other_team_insight": _visualization(MEMBERSHIP_FILTER),
        }
        lines = output.getvalue().splitlines()
        assert lines[lines.index(f"insight {self.status_insight.pk} (team {self.team.pk}):") + 1] == (
            "  a query needs a manual fix"
        )
        assert lines[lines.index(f"insight {self.filter_insight.pk} (team {self.team.pk}):") + 1] == (
            "  still names cohort_membership outside a query this command rewrites"
        )
        verb = "Rewrote" if applied else "Would rewrite"
        assert lines[-1] == f"{verb} 1 rows. 2 rows need a manual check. 0 rows changed while running."

    def test_skips_a_row_edited_after_the_read(self) -> None:
        edited = _visualization(MEMBERSHIP_STATUS)
        rewrite_query_nodes = query_rewrite.rewrite_query_nodes

        def rewrite_after_an_edit(value: Any) -> Any:
            Insight.objects.filter(pk=self.insight.pk).update(query=edited)
            return rewrite_query_nodes(value)

        with patch.object(query_rewrite, "rewrite_query_nodes", side_effect=rewrite_after_an_edit):
            [row] = rewrite_saved_rows(Insight.objects.filter(pk=self.insight.pk), apply=True)

        assert (row.changed, row.written) == (True, False)
        assert Insight.objects.get(pk=self.insight.pk).query == edited
