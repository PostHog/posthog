import json

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.schema import DateRange, EventsNode, InsightVizNode, TrendsFilter, TrendsQuery

from posthog.api.test.dashboards import DashboardAPI
from posthog.models.organization import Organization
from posthog.models.team import Team

from products.dashboards.backend.access import DashboardAccessMethod
from products.dashboards.backend.api.dashboard import DashboardsViewSet
from products.dashboards.backend.constants import RUN_INSIGHTS_MIN_TILE_CHARS
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile, Text
from products.product_analytics.backend.facade.models import Insight, InsightVariable


def _trends_query_dict(event: str = "$pageview", date_from: str = "-7d") -> dict:
    return InsightVizNode(
        source=TrendsQuery(
            series=[EventsNode(event=event)],
            dateRange=DateRange(date_from=date_from),
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

    def test_records_dashboard_access(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="dash")

        with patch("products.dashboards.backend.api.dashboard.record_dashboard_access") as record_access:
            body = self._run(dashboard.id, output_format="json")

        self.assertEqual(body["results"], [])
        record_access.assert_called_once_with(DashboardAccessMethod.HUMAN)
        dashboard.refresh_from_db()
        self.assertIsNone(dashboard.last_accessed_at)

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

    def test_tile_ids_runs_only_the_selected_tiles(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        first_id, _ = self.dashboard_api.create_insight(
            {"name": "A", "query": _trends_query_dict(), "dashboards": [dashboard_id]}
        )
        second_id, _ = self.dashboard_api.create_insight(
            {"name": "B", "query": _trends_query_dict("$autocapture"), "dashboards": [dashboard_id]}
        )
        second_tile = DashboardTile.objects.get(dashboard_id=dashboard_id, insight_id=second_id)

        body = self._run(dashboard_id, output_format="json", tile_ids=str(second_tile.id))

        self.assertEqual([tile["insight"]["id"] for tile in body["results"]], [second_id])
        # The order stays the tile's position on the dashboard, not its index in the subset.
        self.assertEqual(body["results"][0]["order"], 1)
        self.assertNotEqual(first_id, second_id)

    def test_rejects_a_non_numeric_tile_id(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})

        response = self.client.get(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/run_insights/",
            data={"tile_ids": "12,abc"},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)

    def test_rejects_a_tile_id_that_is_not_on_this_dashboard(self) -> None:
        # Dropping the unknown ID instead would answer a stale tile_ids with an empty dashboard.
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        insight_id, _ = self.dashboard_api.create_insight(
            {"name": "A", "query": _trends_query_dict(), "dashboards": [dashboard_id]}
        )
        tile = DashboardTile.objects.get(dashboard_id=dashboard_id, insight_id=insight_id)

        response = self.client.get(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/run_insights/",
            data={"tile_ids": f"{tile.id},{tile.id + 1000}"},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        self.assertIn(str(tile.id + 1000), response.json()["detail"])

    @parameterized.expand([("negative", "-1"), ("too_small_to_hold_a_marker", "10")])
    def test_rejects_an_unusable_max_result_chars(self, _name: str, max_result_chars: str) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})

        response = self.client.get(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/run_insights/",
            data={"max_result_chars": max_result_chars},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)

    def test_optimized_result_is_held_to_the_per_tile_budget(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        self.dashboard_api.create_insight(
            {"name": "A", "query": _trends_query_dict(date_from="-90d"), "dashboards": [dashboard_id]}
        )

        full = self._run(dashboard_id, refresh="blocking", max_result_chars="0")["results"][0]["insight"]["result"]
        if not isinstance(full, str):
            self.skipTest("LLM formatting is unavailable, so there is nothing to bound")

        bounded = self._run(dashboard_id, refresh="blocking", max_result_chars="600")["results"][0]["insight"]["result"]

        self.assertLessEqual(len(bounded), 600)
        self.assertLess(len(bounded), len(full))
        self.assertIn("tile_ids=", bounded)
        # A head-only cut would keep nothing from the recent end of a 90-day table.
        full_lines = [line for line in full.splitlines() if line]
        self.assertTrue(set(full_lines[len(full_lines) // 2 :]) & set(bounded.splitlines()))

    def test_optimized_stops_running_tiles_at_the_response_budget(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        self.dashboard_api.create_insight({"name": "A", "query": _trends_query_dict(), "dashboards": [dashboard_id]})
        self.dashboard_api.create_insight(
            {"name": "B", "query": _trends_query_dict("$autocapture"), "dashboards": [dashboard_id]}
        )

        with patch(
            "products.dashboards.backend.run_insights_output.RUN_INSIGHTS_MAX_TOTAL_CHARS",
            RUN_INSIGHTS_MIN_TILE_CHARS,
        ):
            body = self._run(dashboard_id, refresh="blocking")

        self.assertEqual(len(body["results"]), 2)
        self.assertNotIn("Not run", str(body["results"][0]["insight"]["result"]))
        self.assertIn("Not run", body["results"][1]["insight"]["result"])
        self.assertEqual(
            set(body["results"][1]["insight"].keys()),
            {"id", "short_id", "name", "derived_name", "result"},
        )

    def test_json_format_ignores_max_result_chars(self) -> None:
        # The parameter is documented as optimized-only, so a bad value must not fail a json read.
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        self.dashboard_api.create_insight({"name": "A", "query": _trends_query_dict(), "dashboards": [dashboard_id]})

        body = self._run(dashboard_id, output_format="json", refresh="blocking", max_result_chars="-1")

        self.assertIsInstance(body["results"][0]["insight"]["result"], list)

    def test_bounds_a_result_no_formatter_covers(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        self.dashboard_api.create_insight({"name": "A", "query": _trends_query_dict(), "dashboards": [dashboard_id]})

        with patch.object(DashboardsViewSet, "_format_insight_for_llm", return_value=None):
            body = self._run(dashboard_id, refresh="blocking", max_result_chars=str(RUN_INSIGHTS_MIN_TILE_CHARS))

        result = body["results"][0]["insight"]["result"]
        self.assertIsInstance(result, str)
        self.assertLessEqual(len(result), RUN_INSIGHTS_MIN_TILE_CHARS)
        self.assertIn("tile_ids=", result)

    def test_a_generous_per_tile_budget_cannot_overshoot_the_response_budget(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        self.dashboard_api.create_insight(
            {"name": "A", "query": _trends_query_dict(date_from="-90d"), "dashboards": [dashboard_id]}
        )

        with patch(
            "products.dashboards.backend.run_insights_output.RUN_INSIGHTS_MAX_TOTAL_CHARS",
            RUN_INSIGHTS_MIN_TILE_CHARS,
        ):
            body = self._run(dashboard_id, refresh="blocking", max_result_chars="1000000")

        result = body["results"][0]["insight"]["result"]
        if not isinstance(result, str):
            self.skipTest("LLM formatting is unavailable, so there is nothing to bound")
        rows = [line for line in result.splitlines() if not line.startswith("[")]
        self.assertLessEqual(sum(len(row) + 1 for row in rows), RUN_INSIGHTS_MIN_TILE_CHARS)

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
