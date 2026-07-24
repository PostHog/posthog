import datetime as dt
from types import SimpleNamespace

from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from products.dashboards.backend.models.dashboard import Dashboard
from products.demo.backend.logic.matrix.models import LLM_COSTS_BY_MODEL
from products.demo.backend.logic.products.spikegpt.matrix import SpikeGPTMatrix
from products.demo.backend.logic.products.spikegpt.models import AI_CHARS_PER_SECOND, AI_PROVIDERS


class TestSpikeGPTMatrixSimulation(SimpleTestCase):
    def test_simulation_emits_generations_across_providers_and_tasks(self):
        matrix = SpikeGPTMatrix(
            seed="heatmap-demo",
            now=dt.datetime(2026, 7, 1, tzinfo=dt.UTC),
            days_past=14,
            days_future=0,
            n_clusters=10,
        )
        # Real token counting is slow and tiktoken may hit the network on first load
        matrix.gpt_4o_encoding = SimpleNamespace(encode=lambda text: [0] * max(1, len(text) // 4))  # type: ignore[assignment]
        matrix.simulate()

        all_events = [event for person in matrix.people for event in person.all_events]
        generations = [event for event in all_events if event.event == "$ai_generation"]
        chat_messages = [event for event in all_events if event.event == "sent chat message"]

        assert generations
        assert chat_messages  # User messages must not be misclassified as AI generations

        seen_combinations = set()
        expected_tasks = {task for _, task in AI_CHARS_PER_SECOND}
        for event in generations:
            provider = event.properties["$ai_provider"]
            task = event.properties["$ai_span_name"]
            model = event.properties["$ai_model"]
            assert provider in AI_PROVIDERS
            assert task in expected_tasks
            assert model in LLM_COSTS_BY_MODEL
            assert model in (AI_PROVIDERS[provider]["heavy_model"], AI_PROVIDERS[provider]["light_model"])
            assert event.properties["$ai_latency"] > 0
            seen_combinations.add((provider, task))
        assert seen_combinations == set(AI_CHARS_PER_SECOND)


class TestSpikeGPTProjectSetup(BaseTest):
    def test_set_project_up_creates_llm_performance_dashboard(self):
        matrix = SpikeGPTMatrix(seed="heatmap-demo", n_clusters=0)

        matrix.set_project_up(self.team, self.user)

        dashboard = Dashboard.objects.get(team=self.team, name="LLM performance")
        assert self.team.primary_dashboard == dashboard
        tiles = list(dashboard.tiles.select_related("insight"))
        assert len(tiles) == 3

        heatmap_queries = [
            tile.insight.query for tile in tiles if tile.insight.query.get("kind") == "DataVisualizationNode"
        ]
        assert len(heatmap_queries) == 2
        for query in heatmap_queries:
            assert query["display"] == "TwoDimensionalHeatmap"
            heatmap_settings = query["chartSettings"]["heatmap"]
            sql = query["source"]["query"]
            for axis in ("xAxisColumn", "yAxisColumn", "valueColumn"):
                # Axes are matched to result columns by alias string; drift renders an empty heatmap
                assert f"AS {heatmap_settings[axis]}" in sql
            # The renderer reads gradient stops; a preset id alone falls back to the default gradient
            assert heatmap_settings["gradient"]
