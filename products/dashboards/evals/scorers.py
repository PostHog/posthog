from __future__ import annotations

import asyncio
from typing import Any

from products.dashboards.backend.models.dashboard import Dashboard
from products.posthog_ai.eval_harness.scorers.contract import AsyncOnlyScorerMixin, Score, Scorer
from products.product_analytics.backend.facade.models import Insight


class SavedDashboardContents(AsyncOnlyScorerMixin, Scorer):
    def _name(self) -> str:
        return "saved_dashboard_contents"

    @staticmethod
    def _read_state(team_id: int, name: str) -> dict[str, Any]:
        dashboards = Dashboard.objects.for_team(team_id).filter(deleted=False)
        matching = list(dashboards.filter(name=name))
        return {
            "dashboard_ids": list(dashboards.values_list("id", flat=True)),
            "matching": [
                {"id": dashboard.id, "tiles": list(dashboard.tiles.values("id", "insight_id"))}
                for dashboard in matching
            ],
            "insights": {
                str(row["id"]): row["query"] for row in Insight.objects.for_team(team_id).values("id", "query")
            },
        }

    async def _run_eval_async(
        self, output: dict[str, Any] | None, expected: dict[str, Any] | None = None, **kwargs: Any
    ) -> Score:
        seed = (output or {}).get("seed") or {}
        spec = (expected or {}).get(self._name())
        if not seed.get("team_id") or not seed.get("insights") or not spec:
            return Score(name=self._name(), score=0.0, metadata={"reason": "Missing seed or expected dashboard"})

        state = await asyncio.to_thread(self._read_state, seed["team_id"], spec["name"])
        if len(state["matching"]) != 1:
            return Score(
                name=self._name(), score=0.0, metadata={"reason": "Expected one dashboard with the requested name"}
            )

        dashboard = state["matching"][0]
        tiles = dashboard["tiles"]
        wanted_dashboard_id = seed.get("dashboard_id", dashboard["id"])
        checks = {
            "dashboard_identity": dashboard["id"] == wanted_dashboard_id,
            "no_extra_dashboards": set(state["dashboard_ids"])
            == set(seed["initial_dashboard_ids"]) | {wanted_dashboard_id},
            "exact_insights": sorted(str(tile["insight_id"]) for tile in tiles) == sorted(seed["insights"]),
            "no_new_insights": set(state["insights"])
            == {str(insight_id) for insight_id in seed["initial_insight_ids"]},
            "saved_queries_preserved": all(
                state["insights"].get(key) == query for key, query in seed["insights"].items()
            ),
            "original_tile_preserved": "original_tile_id" not in seed
            or any(
                tile["id"] == seed["original_tile_id"] and tile["insight_id"] == seed["original_tile_insight_id"]
                for tile in tiles
            ),
        }
        failed = [name for name, passed in checks.items() if not passed]
        return Score(name=self._name(), score=float(not failed), metadata={"failed_checks": failed})
