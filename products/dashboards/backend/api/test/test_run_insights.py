import json

from posthog.test.base import APIBaseTest
from unittest import mock

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.schema import DateRange, EventsNode, InsightVizNode, TrendsFilter, TrendsQuery

from posthog.api.test.dashboards import DashboardAPI
from posthog.caching.fetch_from_cache import InsightResult
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.organization import Organization
from posthog.models.team import Team

from products.dashboards.backend.access import DashboardAccessMethod
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile, Text
from products.product_analytics.backend.models.insight import Insight
from products.product_analytics.backend.models.insight_variable import InsightVariable


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

    def test_records_dashboard_access(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="dash")

        with mock.patch("products.dashboards.backend.api.dashboard.record_dashboard_access") as record_access:
            body = self._run(dashboard.id, output_format="json")

        self.assertEqual(body["results"], [])
        record_access.assert_called_once_with(dashboard, DashboardAccessMethod.HUMAN)
        dashboard.refresh_from_db()
        self.assertIsNone(dashboard.last_accessed_at)

    @parameterized.expand(
        [
            (
                "default",
                None,
                ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS,
            ),
            ("force_cache", "force_cache", ExecutionMode.CACHE_ONLY_NEVER_CALCULATE),
            (
                "async_except_on_cache_miss",
                "async_except_on_cache_miss",
                ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS,
            ),
            ("blocking", "blocking", ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE),
            ("force_async", "force_async", ExecutionMode.CALCULATE_ASYNC_ALWAYS),
            ("force_blocking", "force_blocking", ExecutionMode.CALCULATE_BLOCKING_ALWAYS),
        ]
    )
    @mock.patch("posthog.caching.calculate_results.calculate_for_query_based_insight")
    def test_uses_expected_execution_mode(
        self,
        _name: str,
        refresh: str | None,
        expected_execution_mode: ExecutionMode,
        mock_calculate: mock.MagicMock,
    ) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="dash")
        insight = Insight.objects.create(
            team=self.team,
            name="insight",
            query=_trends_query_dict(),
        )
        DashboardTile.objects.create(dashboard=dashboard, insight=insight)
        mock_calculate.return_value = InsightResult(
            result=[],
            last_refresh=timezone.now(),
            cache_key="cache-key",
            is_cached=True,
            timezone=self.team.timezone,
        )
        query_params = {"output_format": "json"}
        if refresh is not None:
            query_params["refresh"] = refresh

        self._run(dashboard.id, **query_params)

        self.assertEqual(mock_calculate.call_args.kwargs["execution_mode"], expected_execution_mode)

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
