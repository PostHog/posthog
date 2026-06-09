"""Scorers for the cohort-creation sandboxed evals.

The behavior under test: when asked to turn a SQL query or a product-analytics
insight into a (static) cohort, the agent should populate the cohort *from the
query* — i.e. call ``cohorts-create`` (or ``cohorts-partial-update``) with
``is_static: true`` and a ``query`` — instead of materializing the actor list
itself and looping ``cohorts-add-persons-to-static-cohort-partial-update`` over
the UUIDs. The query path runs server-side with no row limit; the batching path
caps out and is the failure mode this eval guards against.

All scorers build a single ``LogParser`` from ``output["raw_log"]`` so they work
identically in ``mcp_mode=tools`` (per-tool MCP) and ``mcp_mode=cli`` (single
``exec`` wrapper) — the parser handles exec-unwrapping.
"""

from __future__ import annotations

import re
from typing import Any

from braintrust import Score
from braintrust_core.score import Scorer

from ee.hogai.eval.sandboxed.log_parser import LogParser

__all__ = [
    "COHORTS_ADD_PERSONS_TOOL",
    "COHORTS_CREATE_TOOL",
    "COHORTS_UPDATE_TOOL",
    "CohortFromQueryUsed",
    "QueryTargetsActorColumn",
]

COHORTS_CREATE_TOOL = "cohorts-create"
COHORTS_UPDATE_TOOL = "cohorts-partial-update"
COHORTS_ADD_PERSONS_TOOL = "cohorts-add-persons-to-static-cohort-partial-update"

# Column names ``print_cohort_hogql_query`` accepts for actor extraction, in
# priority order — keep in sync with products/cohorts/backend/models/util.py.
ID_COLUMN_NAMES: tuple[str, ...] = ("person_id", "actor_id", "id", "distinct_id")


def _parser_for(output: dict[str, Any] | None) -> LogParser | None:
    if not output:
        return None
    raw_log = output.get("raw_log")
    if not raw_log:
        return None
    return LogParser(raw_log, initial_prompt=output.get("prompt", "") or "")


def _is_truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)


def _query_population_calls(parser: LogParser | None) -> list[dict[str, Any]]:
    """Successful create/update calls that populate a cohort from a query.

    A create must be static; an update against an existing static cohort does
    not re-send ``is_static``, so for updates we only require a non-empty
    ``query`` dict.
    """
    if parser is None:
        return []
    calls: list[dict[str, Any]] = []
    for tool_name in (COHORTS_CREATE_TOOL, COHORTS_UPDATE_TOOL):
        for call in parser.get_tool_calls(tool_name):
            if call.is_error or not isinstance(call.input, dict):
                continue
            query = call.input.get("query")
            if not isinstance(query, dict) or not query:
                continue
            if tool_name == COHORTS_CREATE_TOOL and not _is_truthy(call.input.get("is_static")):
                continue
            calls.append(call.input)
    return calls


class CohortFromQueryUsed(Scorer):
    """Floor scorer: did the agent populate a cohort from a query?

    Scores 1.0 when at least one successful ``cohorts-create`` (with
    ``is_static`` truthy) or ``cohorts-partial-update`` carried a non-empty
    ``query``. Scores 0.0 otherwise — which catches the regression where the
    agent creates an empty static cohort and tries to batch UUIDs in by hand.
    """

    def __init__(self, *, name: str = "cohort_from_query_used"):
        self._label = name

    def _name(self) -> str:
        return self._label

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output)

    def _evaluate(self, output: dict | None) -> Score:
        parser = _parser_for(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log to parse"})
        calls = _query_population_calls(parser)
        if not calls:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "Agent never created/updated a static cohort from a query"},
            )
        kinds = [c.get("query", {}).get("kind") for c in calls]
        return Score(name=self._name(), score=1.0, metadata={"query_kinds": kinds})


class QueryTargetsActorColumn(Scorer):
    """Did the populating query expose an actor id the backend can resolve?

    A HogQL query must select one of ``person_id`` / ``actor_id`` / ``id`` /
    ``distinct_id`` (or read from the ``events`` / ``persons`` tables, which
    resolve the actor automatically); otherwise the cohort population fails
    with "Could not find a person_id, actor_id, id, or distinct_id column".
    ActorsQuery payloads always resolve, so they pass. Short-circuits to
    ``None`` when no query-population call exists so the floor scorer carries
    the negative signal.
    """

    def __init__(self, *, name: str = "query_targets_actor_column"):
        self._label = name

    def _name(self) -> str:
        return self._label

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output)

    def _evaluate(self, output: dict | None) -> Score:
        parser = _parser_for(output)
        calls = _query_population_calls(parser)
        if not calls:
            return Score(name=self._name(), score=None, metadata={"reason": "No query-population call"})
        last_query = calls[-1].get("query", {})
        kind = last_query.get("kind")
        if kind != "HogQLQuery":
            # ActorsQuery / InsightActorsQuery resolve the actor server-side.
            return Score(name=self._name(), score=1.0, metadata={"kind": kind})
        sql = str(last_query.get("query", "")).lower()
        # Word-boundary match so a column like ``activity_id`` doesn't count as a bare ``id``.
        if (
            any(re.search(rf"\b{col}\b", sql) for col in ID_COLUMN_NAMES)
            or "from events" in sql
            or "from persons" in sql
        ):
            return Score(name=self._name(), score=1.0, metadata={"kind": kind})
        return Score(
            name=self._name(),
            score=0.0,
            metadata={"reason": "HogQL query exposes no resolvable actor column", "sql": sql[:300]},
        )
