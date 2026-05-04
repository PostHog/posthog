import json

from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.schema import DateRange, EventsNode, InsightVizNode, TrendsFilter, TrendsQuery

from posthog.api.test.dashboards import DashboardAPI
from posthog.models import Insight
from posthog.models.insight_variable import InsightVariable
from posthog.models.organization import Organization
from posthog.models.team import Team

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile, Text


def _trends_query_dict(event: str = "$pageview") -> dict:
    return InsightVizNode(
        source=TrendsQuery(
            series=[EventsNode(event=event)],
            dateRange=DateRange(date_from="-7d"),
            trendsFilter=TrendsFilter(display="ActionsLineGraph"),
        ),
    ).model_dump()


class TestDashboardRunInsights(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)

    def _run(self, dashboard_id: int, **query_params) -> dict:
        response = self.client.get(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/run_insights/",
            data=query_params,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        return response.json()

    def test_returns_one_result_per_insight_tile(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        insight_a_id, _ = self.dashboard_api.create_insight(
            {"name": "A", "query": _trends_query_dict(), "dashboards": [dashboard_id]}
        )
        insight_b_id, _ = self.dashboard_api.create_insight(
            {"name": "B", "query": _trends_query_dict("$autocapture"), "dashboards": [dashboard_id]}
        )

        body = self._run(dashboard_id, output_format="json")

        self.assertEqual(len(body["results"]), 2)
        ids = {tile["insight"]["id"] for tile in body["results"]}
        self.assertEqual(ids, {insight_a_id, insight_b_id})

        for tile in body["results"]:
            self.assertIn("id", tile)
            self.assertIn("order", tile)
            insight = tile["insight"]
            self.assertEqual(
                set(insight.keys()),
                {"id", "short_id", "name", "derived_name", "result"},
            )

    def test_json_format_returns_raw_query_results(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        self.dashboard_api.create_insight({"name": "A", "query": _trends_query_dict(), "dashboards": [dashboard_id]})

        body = self._run(dashboard_id, output_format="json", refresh="blocking")

        result = body["results"][0]["insight"]["result"]
        self.assertIsInstance(result, list)
        self.assertGreaterEqual(len(result), 1)
        self.assertIn("data", result[0])
        self.assertIn("labels", result[0])

    def test_optimized_format_returns_formatted_string(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        self.dashboard_api.create_insight({"name": "A", "query": _trends_query_dict(), "dashboards": [dashboard_id]})

        # optimized is the default
        body = self._run(dashboard_id, refresh="blocking")

        result = body["results"][0]["insight"]["result"]
        # format_query_results_for_llm returns a text table when EE is available;
        # when it falls back it leaves the raw list in place — accept either.
        self.assertTrue(isinstance(result, str) or isinstance(result, list))
        if isinstance(result, str):
            self.assertIn("|", result)

    def test_skips_text_tiles(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        self.dashboard_api.create_insight({"name": "A", "query": _trends_query_dict(), "dashboards": [dashboard_id]})

        text = Text.objects.create(team=self.team, body="I am text")
        DashboardTile.objects.create(dashboard_id=dashboard_id, text=text)

        body = self._run(dashboard_id, output_format="json")

        self.assertEqual(len(body["results"]), 1)
        self.assertIsNotNone(body["results"][0]["insight"])

    def test_skips_insights_without_a_query(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="dash")
        with_query_id, _ = self.dashboard_api.create_insight(
            {"name": "has query", "query": _trends_query_dict(), "dashboards": [dashboard.pk]}
        )
        legacy = Insight.objects.create(
            team=self.team,
            name="no query",
            filters={"events": [{"id": "$pageview"}]},
        )
        DashboardTile.objects.create(dashboard=dashboard, insight=legacy)

        body = self._run(dashboard.pk, output_format="json")

        self.assertEqual(len(body["results"]), 1)
        self.assertEqual(body["results"][0]["insight"]["id"], with_query_id)

    def test_empty_dashboard_returns_empty_results(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "empty"})

        body = self._run(dashboard_id)

        self.assertEqual(body, {"results": []})

    def test_respects_team_scoping(self) -> None:
        other_team = Team.objects.create(organization=Organization.objects.create(name="other"))
        dashboard = Dashboard.objects.create(team=other_team, name="other dash")

        response = self.client.get(
            f"/api/projects/{self.team.id}/dashboards/{dashboard.pk}/run_insights/",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_tile_order_follows_sm_layout(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        first_id, _ = self.dashboard_api.create_insight(
            {"name": "first", "query": _trends_query_dict(), "dashboards": [dashboard_id]}
        )
        second_id, _ = self.dashboard_api.create_insight(
            {"name": "second", "query": _trends_query_dict("$autocapture"), "dashboards": [dashboard_id]}
        )

        # Swap layout positions so `second` is top-left.
        tiles = {t.insight_id: t for t in DashboardTile.objects.filter(dashboard_id=dashboard_id)}
        tiles[second_id].layouts = {"sm": {"x": 0, "y": 0, "w": 6, "h": 5}}
        tiles[second_id].save()
        tiles[first_id].layouts = {"sm": {"x": 6, "y": 0, "w": 6, "h": 5}}
        tiles[first_id].save()

        body = self._run(dashboard_id, output_format="json")

        self.assertEqual([tile["insight"]["id"] for tile in body["results"]], [second_id, first_id])
        self.assertEqual([tile["order"] for tile in body["results"]], [0, 1])

    def test_variables_override_query_param_applies_to_insight_results(self) -> None:
        # Locks the contract documented by the VARIABLES_OVERRIDE_PARAM @extend_schema annotation:
        # an MCP / API caller passing variables_override with the documented {code_name, variableId, value}
        # shape gets results computed against the overridden value, not the persisted default.
        # Without this test the override path through DashboardTileResultSerializer →
        # InsightResultSerializer's inherited SerializerMethodField is fragile under future refactors.
        variable = InsightVariable.objects.create(
            team=self.team, name="Threshold", code_name="threshold", default_value=10, type="Number"
        )
        dashboard = Dashboard.objects.create(team=self.team, name="dash")
        insight = Insight.objects.create(
            team=self.team,
            name="threshold check",
            query={
                "kind": "DataVisualizationNode",
                "source": {
                    "kind": "HogQLQuery",
                    "query": "SELECT {variables.threshold}",
                    "variables": {
                        str(variable.id): {
                            "code_name": variable.code_name,
                            "variableId": str(variable.id),
                        }
                    },
                },
                "display": "BoldNumber",
            },
        )
        DashboardTile.objects.create(insight=insight, dashboard=dashboard)

        # Without override → default value.
        baseline = self._run(dashboard.pk, output_format="json", refresh="blocking")
        self.assertEqual(baseline["results"][0]["insight"]["result"][0][0], 10)

        # With override → overridden value.
        overridden = self._run(
            dashboard.pk,
            output_format="json",
            refresh="blocking",
            variables_override=json.dumps(
                {
                    str(variable.id): {
                        "code_name": variable.code_name,
                        "variableId": str(variable.id),
                        "value": 99,
                    }
                }
            ),
        )
        self.assertEqual(overridden["results"][0]["insight"]["result"][0][0], 99)
