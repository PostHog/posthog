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
from products.posthog_ai.eval_harness.log_parser import LogParser, ToolCall
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


WIDGET_WRITE_TOOLS = frozenset({"dashboard-widgets-batch-add", "dashboard-widgets-batch-update", "dashboard-update"})
WIDGET_CATALOG_TOOL = "dashboard-widget-catalog-list"


class WidgetFirstWriteValid(Scorer):
    """Compare this score across widget tool schema changes.

    A schema that hides the config keys must not cost the agent a rejected first write.
    """

    def _name(self) -> str:
        return "widget_first_write_valid"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        if not output or not output.get("raw_log"):
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})
        parser = LogParser.cached(output["raw_log"], initial_prompt=output.get("prompt", "") or "")
        calls = parser.get_tool_calls()
        writes = [call for call in calls if _is_widget_write(call)]
        if not writes:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No widget write call"})

        first_success = next((index for index, call in enumerate(writes) if not call.is_error), None)
        catalog_positions = [call.position for call in calls if call.name == WIDGET_CATALOG_TOOL and not call.is_error]
        return Score(
            name=self._name(),
            score=float(not writes[0].is_error),
            metadata={
                "write_attempts": len(writes),
                "failed_writes": sum(call.is_error for call in writes),
                "failed_before_first_success": len(writes) if first_success is None else first_success,
                "write_tools": [call.name for call in writes],
                "catalog_before_first_write": any(position < writes[0].position for position in catalog_positions),
            },
        )


class SavedWidgetState(AsyncOnlyScorerMixin, Scorer):
    def _name(self) -> str:
        return "saved_widget_state"

    @staticmethod
    def _read_state(team_id: int, dashboard_id: int, widget_type: str) -> list[dict[str, Any]]:
        dashboard = Dashboard.objects.get(team_id=team_id, id=dashboard_id)
        rows = (
            dashboard.tiles.exclude(deleted=True)
            .filter(widget__widget_type=widget_type)
            .values("id", "layouts", "widget_id", "widget__config")
        )
        return [dict(row) for row in rows]

    async def _run_eval_async(
        self, output: dict[str, Any] | None, expected: dict[str, Any] | None = None, **kwargs: Any
    ) -> Score:
        seed = (output or {}).get("seed") or {}
        spec = (expected or {}).get(self._name())
        if not seed.get("team_id") or not seed.get("dashboard_id") or not spec:
            return Score(name=self._name(), score=0.0, metadata={"reason": "Missing seed or expected widget"})

        tiles = await asyncio.to_thread(self._read_state, seed["team_id"], seed["dashboard_id"], spec["widget_type"])
        if len(tiles) != 1:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": f"Expected one {spec['widget_type']} tile", "tile_count": len(tiles)},
            )

        tile = tiles[0]
        config = tile["widget__config"] or {}
        seeded_config = seed.get("widget_config") or {}
        checks = {
            "requested_config": all(
                _same_value(config.get(key), value) for key, value in spec.get("config", {}).items()
            ),
            "preserved_config": config == seeded_config
            if spec.get("preserved") == "all"
            else all(_same_value(config.get(key), seeded_config.get(key)) for key in spec.get("preserved", [])),
            "same_widget": "widget_id" not in seed or str(tile["widget_id"]) == str(seed["widget_id"]),
            "layout_width": "layout_width" not in spec
            or ((tile["layouts"] or {}).get("sm") or {}).get("w") == spec["layout_width"],
        }
        failed = [name for name, passed in checks.items() if not passed]
        return Score(name=self._name(), score=float(not failed), metadata={"failed_checks": failed, "config": config})


def _is_widget_write(call: ToolCall) -> bool:
    # dashboard-update also edits dashboard metadata, which does not touch any widget.
    if call.name == "dashboard-update":
        return "tiles" in call.input
    return call.name in WIDGET_WRITE_TOOLS


def _same_value(actual: Any, wanted: Any) -> bool:
    # The agent may list multi-select values in any order.
    if isinstance(actual, list) and isinstance(wanted, list):
        return sorted(map(str, actual)) == sorted(map(str, wanted))
    return actual == wanted
