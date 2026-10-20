from __future__ import annotations

import asyncio
from typing import Any

from pydantic import ValidationError

from posthog.hogql.errors import ExposedHogQLError

from posthog.errors import ExposedCHQueryError
from posthog.hogql_queries.apply_dashboard_filters import (
    apply_dashboard_filters_to_dict,
    resolve_effective_dashboard_filters,
)
from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models.team import Team

from products.dashboards.backend.models.dashboard import Dashboard
from products.posthog_ai.eval_harness.scorers.contract import AsyncOnlyScorerMixin, Score, Scorer
from products.product_analytics.backend.facade.models import Insight

# Both ranges are longer than the 30-day window a prompt can ask for, so a query that hardcodes that
# window returns the same rows for both and fails.
DASHBOARD_DATE_RANGES = ("-60d", "-90d")


class SavedDashboardContents(AsyncOnlyScorerMixin, Scorer):
    def _name(self) -> str:
        return "saved_dashboard_contents"

    @staticmethod
    def _read_state(team_id: int, name: str) -> dict[str, Any]:
        dashboards = Dashboard.objects.filter(team_id=team_id, deleted=False)
        matching = list(dashboards.filter(name=name))
        return {
            "dashboard_ids": list(dashboards.values_list("id", flat=True)),
            "matching": [
                {"id": dashboard.id, "tiles": list(dashboard.tiles.values("id", "insight_id"))}
                for dashboard in matching
            ],
            "insights": {
                str(row["id"]): row["query"] for row in Insight.objects.filter(team_id=team_id).values("id", "query")
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


def sql_source(query: Any) -> dict[str, Any] | None:
    if not isinstance(query, dict):
        return None
    if query.get("kind") == "HogQLQuery":
        return query
    source = query.get("source")
    if isinstance(source, dict) and source.get("kind") == "HogQLQuery":
        return source
    return None


class SQLTilesFollowDashboardDateRange(AsyncOnlyScorerMixin, Scorer):
    def _name(self) -> str:
        return "sql_tiles_follow_dashboard_date_range"

    @staticmethod
    def _results_for_date_range(
        source: dict[str, Any], date_from: str, tile_filters_override: dict[str, Any] | None, team: Team
    ) -> str:
        effective = resolve_effective_dashboard_filters(source, {"date_from": date_from}, tile_filters_override)
        query = apply_dashboard_filters_to_dict(effective.query, effective.filters, team)
        # Grouped SQL without ORDER BY can return the same rows in a different order.
        return repr(sorted(repr(row) for row in get_query_runner(query, team).calculate().results))

    @classmethod
    def _read_state(cls, team_id: int, name: str) -> dict[str, Any]:
        team = Team.objects.get(id=team_id)
        matching = list(Dashboard.objects.filter(team_id=team_id, name=name, deleted=False))
        sql_tiles: list[dict[str, Any]] = []
        if len(matching) == 1:
            tiles = matching[0].tiles.filter(insight__isnull=False, insight__deleted=False).select_related("insight")
            for tile in tiles:
                source = sql_source(tile.insight.query)
                if source is None:
                    continue
                state: dict[str, Any] = {
                    "insight_id": tile.insight_id,
                    "uses_filters_placeholder": "{filters" in str(source.get("query", "")),
                }
                try:
                    state["results"] = [
                        cls._results_for_date_range(source, date_from, tile.filters_overrides, team)
                        for date_from in DASHBOARD_DATE_RANGES
                    ]
                # Other exceptions are infrastructure failures, so they reach the harness as scorer errors.
                except (ExposedHogQLError, ExposedCHQueryError, ValidationError) as error:
                    state["error"] = repr(error)
                sql_tiles.append(state)
        return {"matching_count": len(matching), "sql_tiles": sql_tiles}

    async def _run_eval_async(
        self, output: dict[str, Any] | None, expected: dict[str, Any] | None = None, **kwargs: Any
    ) -> Score:
        seed = (output or {}).get("seed") or {}
        spec = (expected or {}).get(self._name())
        if not seed.get("team_id") or not spec:
            return Score(name=self._name(), score=0.0, metadata={"reason": "Missing seed or expected dashboard"})

        state = await asyncio.to_thread(self._read_state, seed["team_id"], spec["name"])
        if state["matching_count"] != 1:
            return Score(
                name=self._name(), score=0.0, metadata={"reason": "Expected one dashboard with the requested name"}
            )

        tiles = state["sql_tiles"]
        follows = {str(tile["insight_id"]): "error" not in tile and len(set(tile["results"])) > 1 for tile in tiles}
        required = max(len(tiles), spec.get("min_sql_tiles", 1))
        return Score(
            name=self._name(),
            score=sum(follows.values()) / required,
            metadata={
                "sql_tile_count": len(tiles),
                "follows_date_range": follows,
                "uses_filters_placeholder": {
                    str(tile["insight_id"]): tile["uses_filters_placeholder"] for tile in tiles
                },
                "errors": {str(tile["insight_id"]): tile["error"] for tile in tiles if "error" in tile},
            },
        )
