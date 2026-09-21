from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from django.test import SimpleTestCase

from posthog.hogql.query import execute_hogql_query

from posthog.models.tag import Tag

from products.ai_observability.backend.dashboard_templates import get_ai_observability_default_template
from products.ai_observability.backend.model_breakdown import (
    MODEL_BREAKDOWN_DESCRIPTION,
    NORMALIZED_MODEL_BREAKDOWN_HOGQL,
    RAW_MODEL_BREAKDOWN_FILTER,
)
from products.ai_observability.backend.model_breakdown_backfill import MODEL_TILE_NAMES, fold_model_breakdown
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.product_analytics.backend.models.insight import Insight


class TestModelBreakdownBackfill(APIBaseTest):
    def _create_ai_observability_dashboard(self, *, tag: str = "llm-analytics") -> Dashboard:
        dashboard = Dashboard.objects.create(team=self.team, name="AI observability", creation_mode="unlisted")
        dashboard.tagged_items.create(tag=Tag.objects.create(name=tag, team=self.team))
        return dashboard

    def _add_tile(self, dashboard: Dashboard, name: str, breakdown_filter: dict) -> Insight:
        insight = Insight.objects.create(
            team=self.team,
            name=name,
            query={
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [{"kind": "EventsNode", "event": "$ai_generation"}],
                    "breakdownFilter": breakdown_filter,
                },
            },
        )
        DashboardTile.objects.create(dashboard=dashboard, insight=insight)
        return insight

    def test_folds_the_template_tiles_and_leaves_an_edited_one_alone(self) -> None:
        dashboard = self._create_ai_observability_dashboard()
        cost_tile = self._add_tile(dashboard, MODEL_TILE_NAMES[0], dict(RAW_MODEL_BREAKDOWN_FILTER))
        edited_tile = self._add_tile(
            dashboard, MODEL_TILE_NAMES[1], {"breakdown_type": "event", "breakdown": "$ai_provider"}
        )

        report = fold_model_breakdown(apply=True)

        assert report.folded == (cost_tile.id,)
        assert report.skipped == (edited_tile.id,)

        cost_tile.refresh_from_db()
        assert cost_tile.query
        assert cost_tile.query["source"]["breakdownFilter"] == {
            "breakdown_type": "hogql",
            "breakdown": NORMALIZED_MODEL_BREAKDOWN_HOGQL,
        }
        assert cost_tile.description == MODEL_BREAKDOWN_DESCRIPTION
        assert cost_tile.query_metadata is not None

        edited_tile.refresh_from_db()
        assert edited_tile.query
        assert edited_tile.query["source"]["breakdownFilter"]["breakdown"] == "$ai_provider"

    def test_reports_without_writing_until_apply(self) -> None:
        dashboard = self._create_ai_observability_dashboard()
        tile = self._add_tile(dashboard, MODEL_TILE_NAMES[0], dict(RAW_MODEL_BREAKDOWN_FILTER))

        report = fold_model_breakdown()

        assert report.folded == (tile.id,)
        tile.refresh_from_db()
        assert tile.query
        assert tile.query["source"]["breakdownFilter"] == RAW_MODEL_BREAKDOWN_FILTER

    def test_ignores_a_model_tile_outside_an_ai_observability_dashboard(self) -> None:
        dashboard = self._create_ai_observability_dashboard(tag="mcp-analytics")
        self._add_tile(dashboard, MODEL_TILE_NAMES[0], dict(RAW_MODEL_BREAKDOWN_FILTER))

        assert fold_model_breakdown(apply=True).candidates == 0


class TestModelBreakdownTemplateTiles(SimpleTestCase):
    def test_the_backfill_names_the_tiles_the_template_breaks_down_by_model(self) -> None:
        template_tiles = {
            tile["name"]: tile["query"]["source"]
            for tile in get_ai_observability_default_template().tiles or []
            if tile["type"] == "INSIGHT"
        }

        for name in MODEL_TILE_NAMES:
            assert template_tiles[name]["breakdownFilter"]["breakdown"] == NORMALIZED_MODEL_BREAKDOWN_HOGQL


class TestNormalizedModelBreakdownExpression(ClickhouseTestMixin, APIBaseTest):
    def test_folds_the_provider_prefix_and_the_case_of_one_model(self) -> None:
        for model in ("gpt-5", "openai/gpt-5", "OpenAI/GPT-5", "gpt-5-mini"):
            _create_event(
                team=self.team,
                event="$ai_generation",
                distinct_id="user",
                properties={"$ai_model": model},
            )
        flush_persons_and_events()

        response = execute_hogql_query(
            f"SELECT {NORMALIZED_MODEL_BREAKDOWN_HOGQL} AS model, count() FROM events GROUP BY model ORDER BY model",
            self.team,
        )

        assert response.results == [("gpt-5", 3), ("gpt-5-mini", 1)]
