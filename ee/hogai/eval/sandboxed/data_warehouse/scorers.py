"""Scorers for the data-warehouse ``information_schema`` navigation eval.

All scorers are mode-agnostic: they read tool calls through ``LogParser``
(tools-mode and CLI exec both normalize to ``execute-sql``) and the agent's
final text. Each self-skips with ``Score(score=None)`` when its ``expected`` key
is absent, so one global scorer list works across every case — Braintrust drops
``None`` from per-metric aggregates.

Targets/answers come from ``output["seed"]`` (set by ``seed_warehouse_schema``);
cases opt a scorer in by listing its ``_name()`` in ``expected``. The scorers
degrade gracefully when the queryable needle's backing data is unavailable:
discovery/search/relationship grading never touches object storage.
"""

from __future__ import annotations

from typing import Any

from braintrust import Score
from braintrust_core.score import Scorer

from ee.hogai.eval.sandboxed.log_parser import LogParser, ToolCall
from ee.hogai.eval.sandboxed.product_analytics.scorers import (
    GRADED_ALIGNMENT_CHOICE_SCORES,
    JUDGE_MODEL,
    JudgedScorer,
    parser_for,
    user_prompt,
)
from ee.hogai.eval.sandboxed.sql.scorers import _truncate_result_for_judge, extract_last_execute_sql_call

__all__ = [
    "InformationSchemaQueried",
    "InformationSchemaBeforeAnswer",
    "AgenticSearchUsed",
    "NeedleTableIdentified",
    "NeedleValueRetrieved",
    "RelationshipDiscovery",
    "StaleTableAvoided",
    "JoinPathTraversed",
    "AnswerQueryRanWhenExpected",
    "WarehouseAnswerCorrectness",
]

SQL_TOOL = "execute-sql"
_INFO_SCHEMA = "information_schema"


def _query_text(call: ToolCall) -> str:
    query = call.input.get("query") if isinstance(call.input, dict) else None
    return query.lower() if isinstance(query, str) else ""


def _is_info_schema(call: ToolCall) -> bool:
    return _INFO_SCHEMA in _query_text(call)


def _successful_sql(parser: LogParser) -> list[ToolCall]:
    return sorted((c for c in parser.get_tool_calls(SQL_TOOL) if not c.is_error), key=lambda c: c.position)


def _seed(output: dict[str, Any] | None) -> dict[str, Any]:
    seed = output.get("seed") if output else None
    return seed if isinstance(seed, dict) else {}


def _requested(expected: dict | None, name: str) -> bool:
    return isinstance(expected, dict) and name in expected


def _final_message(output: dict[str, Any] | None) -> str:
    message = (output or {}).get("last_message") or ""
    return message if isinstance(message, str) else str(message)


class InformationSchemaQueried(Scorer):
    """Binary: did the agent discover the schema via ``system.information_schema``?

    The primary capability-#1 check — never needs row data, so it grades the same
    whether or not the warehouse is queryable. Opt-in via ``expected`` key.
    """

    def _name(self) -> str:
        return "information_schema_queried"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _evaluate(self, output: dict | None, expected: dict | None = None) -> Score:
        if not output:
            return Score(name=self._name(), score=None, metadata={"reason": "No output"})
        if not _requested(expected, self._name()):
            return Score(name=self._name(), score=None, metadata={"reason": "not requested"})
        parser = parser_for(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})
        hits = [c for c in _successful_sql(parser) if _is_info_schema(c)]
        return Score(name=self._name(), score=1.0 if hits else 0.0, metadata={"info_schema_queries": len(hits)})


class InformationSchemaBeforeAnswer(Scorer):
    """Binary: was every non-discovery ``execute-sql`` preceded by an info_schema query?

    DWH adaptation of the ``system.*`` discipline scorer: warehouse tables are
    bare-named, so the "answer" query is simply any successful ``execute-sql`` that
    is not an ``information_schema`` lookup. ``None`` when no answer query ran.
    """

    def _name(self) -> str:
        return "information_schema_before_answer"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _evaluate(self, output: dict | None, expected: dict | None = None) -> Score:
        if not output:
            return Score(name=self._name(), score=None, metadata={"reason": "No output"})
        if not _requested(expected, self._name()):
            return Score(name=self._name(), score=None, metadata={"reason": "not requested"})
        parser = parser_for(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        seen_discovery = False
        offenders: list[str] = []
        answer_calls = 0
        for call in _successful_sql(parser):
            if _is_info_schema(call):
                seen_discovery = True
                continue
            answer_calls += 1
            if not seen_discovery:
                offenders.append(call.call_id)

        if answer_calls == 0:
            return Score(name=self._name(), score=None, metadata={"reason": "No non-discovery answer query ran"})
        if offenders:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "answer query ran before discovery", "offenders": offenders},
            )
        return Score(name=self._name(), score=1.0, metadata={"answer_calls": answer_calls})


class AgenticSearchUsed(Scorer):
    """Binary: did discovery filter the catalog instead of dumping it?

    Inspects the SQL text of ``information_schema`` queries. A *filtered* query has
    a ``WHERE`` referencing a real metadata column or using a pattern predicate; a
    *dump* selects from ``tables``/``columns`` with no ``WHERE``. When the case sets
    ``require_pattern``, only a pattern predicate (LIKE/ILIKE/match) counts.
    """

    _FILTERABLE = (
        "table_name",
        "table_type",
        "table_schema",
        "description",
        "data_type",
        "column_name",
        "field_kind",
        "source_table",
        "target_table",
        "relationship_kind",
    )
    _PATTERNS = ("like", "ilike", "match(", "multisearchany", "positioncaseinsensitive")

    def _name(self) -> str:
        return "agentic_search_used"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _evaluate(self, output: dict | None, expected: dict | None = None) -> Score:
        if not output:
            return Score(name=self._name(), score=None, metadata={"reason": "No output"})
        if not _requested(expected, self._name()):
            return Score(name=self._name(), score=None, metadata={"reason": "not requested"})
        spec = expected.get(self._name()) if isinstance(expected, dict) else None
        spec = spec if isinstance(spec, dict) else {}
        parser = parser_for(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        info_queries = [_query_text(c) for c in _successful_sql(parser) if _is_info_schema(c)]
        if not info_queries:
            return Score(name=self._name(), score=None, metadata={"reason": "No information_schema query ran"})

        filtered = dumps = patterns = 0
        for query in info_queries:
            has_where = " where " in query
            uses_pattern = any(p in query for p in self._PATTERNS)
            refs_column = any(col in query for col in self._FILTERABLE)
            if uses_pattern:
                patterns += 1
            if has_where and (refs_column or uses_pattern):
                filtered += 1
            elif not has_where and ("information_schema.tables" in query or "information_schema.columns" in query):
                dumps += 1

        metadata = {"filtered": filtered, "dumps": dumps, "patterns": patterns, "total": len(info_queries)}
        if spec.get("require_pattern"):
            return Score(name=self._name(), score=1.0 if patterns else 0.0, metadata=metadata)
        return Score(name=self._name(), score=1.0 if filtered else 0.0, metadata=metadata)


class NeedleTableIdentified(Scorer):
    """Binary: did the agent name the correct needle table (queryability-safe)?

    Resolves the target table from ``expected[name]["table"]`` or, when the case
    points at a seed entry, ``seed[expected[name]["seed_key"]]["table"]``. Passes
    when the table appears in the final message or any ``execute-sql`` text.
    """

    def _name(self) -> str:
        return "needle_table_identified"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _resolve_table(self, output: dict | None, expected: dict | None) -> str | None:
        spec = expected.get(self._name()) if isinstance(expected, dict) else None
        if not isinstance(spec, dict):
            return None
        if isinstance(spec.get("table"), str):
            return spec["table"]
        seed_key = spec.get("seed_key")
        if isinstance(seed_key, str):
            entry = _seed(output).get(seed_key)
            if isinstance(entry, dict) and isinstance(entry.get("table"), str):
                return entry["table"]
        return None

    def _evaluate(self, output: dict | None, expected: dict | None = None) -> Score:
        if not output:
            return Score(name=self._name(), score=None, metadata={"reason": "No output"})
        if not _requested(expected, self._name()):
            return Score(name=self._name(), score=None, metadata={"reason": "not requested"})
        table = self._resolve_table(output, expected)
        if not table:
            return Score(name=self._name(), score=None, metadata={"reason": "no table configured"})
        needle = table.lower()
        if needle in _final_message(output).lower():
            return Score(name=self._name(), score=1.0, metadata={"matched_via": "final_message", "table": table})
        parser = parser_for(output)
        if parser is not None:
            for call in _successful_sql(parser):
                if needle in _query_text(call):
                    return Score(name=self._name(), score=1.0, metadata={"matched_via": "sql_ref", "table": table})
        return Score(name=self._name(), score=0.0, metadata={"table": table})


class NeedleValueRetrieved(Scorer):
    """Binary: does the retrieval-needle value appear in the SQL result or final answer?

    The graded value defaults to the retrieval needle's ``answer`` (the JSON
    secret_code), but a case can override it via ``expected[name]["value"]`` — e.g.
    the duck-typing case grades the numeric max, not the secret_code.

    Self-skips (``None``) when the queryable needle could not be created (object
    storage unavailable) — the value is genuinely unreachable then. Otherwise the
    value must appear in the last non-discovery ``execute-sql`` result (preferred)
    or the final message (``degraded`` fallback).
    """

    def _name(self) -> str:
        return "needle_value_retrieved"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _evaluate(self, output: dict | None, expected: dict | None = None) -> Score:
        if not output:
            return Score(name=self._name(), score=None, metadata={"reason": "No output"})
        if not _requested(expected, self._name()):
            return Score(name=self._name(), score=None, metadata={"reason": "not requested"})
        retrieval = _seed(output).get("retrieval_needle")
        if not isinstance(retrieval, dict):
            return Score(name=self._name(), score=None, metadata={"reason": "no retrieval needle configured"})
        if not retrieval.get("queryable"):
            return Score(name=self._name(), score=None, metadata={"reason": "needle not queryable in this env"})

        spec = expected.get(self._name()) if isinstance(expected, dict) else None
        override = spec.get("value") if isinstance(spec, dict) else None
        value = override if isinstance(override, str) else retrieval.get("answer")
        if not isinstance(value, str):
            return Score(name=self._name(), score=None, metadata={"reason": "no needle value configured"})

        needle = value.lower()
        call = extract_last_execute_sql_call(output)
        if call and needle in (call.get("result") or "").lower():
            return Score(name=self._name(), score=1.0, metadata={"matched_via": "sql_result", "needle": needle})
        if needle in _final_message(output).lower():
            return Score(
                name=self._name(),
                score=1.0,
                metadata={"matched_via": "final_message", "needle": needle, "degraded": call is None},
            )
        return Score(
            name=self._name(),
            score=0.0,
            metadata={"needle": needle, "answer_query_ran": call is not None},
        )


class RelationshipDiscovery(Scorer):
    """Binary: did the agent discover the join and reference both tables?

    Reads the pair from ``seed["relationship_needle"]``. Passes when the agent
    queried ``information_schema.relationships`` (or co-referenced both tables in
    one query) AND both tables appear in a query or the final message.
    """

    def _name(self) -> str:
        return "relationship_discovery"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _evaluate(self, output: dict | None, expected: dict | None = None) -> Score:
        if not output:
            return Score(name=self._name(), score=None, metadata={"reason": "No output"})
        if not _requested(expected, self._name()):
            return Score(name=self._name(), score=None, metadata={"reason": "not requested"})
        rel = _seed(output).get("relationship_needle")
        if not isinstance(rel, dict) or not rel.get("source") or not rel.get("target"):
            return Score(name=self._name(), score=None, metadata={"reason": "no relationship needle configured"})
        parser = parser_for(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        source, target = rel["source"].lower(), rel["target"].lower()
        calls = _successful_sql(parser)
        rel_queried = any("information_schema.relationships" in _query_text(c) for c in calls)
        joined_in_sql = any(source in _query_text(c) and target in _query_text(c) for c in calls)
        final = _final_message(output).lower()
        named_in_message = source in final and target in final

        discovered = rel_queried or joined_in_sql
        referenced = joined_in_sql or named_in_message
        ok = discovered and referenced
        return Score(
            name=self._name(),
            score=1.0 if ok else 0.0,
            metadata={
                "relationships_queried": rel_queried,
                "joined_in_sql": joined_in_sql,
                "named_in_message": named_in_message,
                "degraded": ok and not joined_in_sql,
            },
        )


class StaleTableAvoided(Scorer):
    """Binary: did the agent pick the live table over the superseded decoy?

    Two near-identical tables share a topic; only the annotation says which is
    current. Reads the pair from ``seed["relevancy_needle"]`` (``current`` /
    ``stale``). Passes when the final answer surfaces the current table AND does not
    leave the stale table standing as a usable option — naming the stale table is
    fine only when the answer flags it as deprecated/superseded. Fails when the
    agent recommends the stale table or never finds the current one.
    """

    _DEPRECATION_CUES = (
        "deprecat",
        "supersed",
        "no longer",
        "frozen",
        "stale",
        "outdated",
        "do not use",
        "don't use",
        "legacy",
        "replaced",
        "not refreshed",
        "instead of",
    )

    def _name(self) -> str:
        return "stale_table_avoided"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _evaluate(self, output: dict | None, expected: dict | None = None) -> Score:
        if not output:
            return Score(name=self._name(), score=None, metadata={"reason": "No output"})
        if not _requested(expected, self._name()):
            return Score(name=self._name(), score=None, metadata={"reason": "not requested"})
        rel = _seed(output).get("relevancy_needle")
        if not isinstance(rel, dict) or not rel.get("current") or not rel.get("stale"):
            return Score(name=self._name(), score=None, metadata={"reason": "no relevancy needle configured"})

        current, stale = rel["current"].lower(), rel["stale"].lower()
        final = _final_message(output).lower()
        current_named = current in final
        stale_named = stale in final
        # Only count the stale name as "deprecation-flagged" when a cue word actually
        # appears in the answer — otherwise a bare mention reads as recommending it.
        stale_flagged = stale_named and any(cue in final for cue in self._DEPRECATION_CUES)

        ok = current_named and (not stale_named or stale_flagged)
        return Score(
            name=self._name(),
            score=1.0 if ok else 0.0,
            metadata={
                "current_named": current_named,
                "stale_named": stale_named,
                "stale_flagged": stale_flagged,
            },
        )


class JoinPathTraversed(Scorer):
    """Binary: did the agent assemble the full multi-hop join path?

    Reads the ordered path from ``seed["chain_needle"]`` (``tables``: source-first;
    ``keys``: per hop). Passes when the agent queried
    ``information_schema.relationships`` AND every table on the path appears in a
    query or the final answer — i.e. it followed the relationships out across more
    than one hop rather than stopping at the first. Join keys named are tracked in
    metadata but not required (table coverage is the load-bearing signal).
    """

    def _name(self) -> str:
        return "join_path_traversed"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _evaluate(self, output: dict | None, expected: dict | None = None) -> Score:
        if not output:
            return Score(name=self._name(), score=None, metadata={"reason": "No output"})
        if not _requested(expected, self._name()):
            return Score(name=self._name(), score=None, metadata={"reason": "not requested"})
        chain = _seed(output).get("chain_needle")
        tables = chain.get("tables") if isinstance(chain, dict) else None
        if not isinstance(tables, list) or len(tables) < 3:
            return Score(name=self._name(), score=None, metadata={"reason": "no chain needle configured"})
        parser = parser_for(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        calls = _successful_sql(parser)
        rel_queried = any("information_schema.relationships" in _query_text(c) for c in calls)
        final = _final_message(output).lower()
        sql_blob = " ".join(_query_text(c) for c in calls)
        named = [t for t in tables if t.lower() in final or t.lower() in sql_blob]
        all_named = len(named) == len(tables)

        keys = chain.get("keys") if isinstance(chain, dict) else []
        keys = keys if isinstance(keys, list) else []
        keys_named = [k for k in keys if k.lower() in final]

        ok = rel_queried and all_named
        return Score(
            name=self._name(),
            score=1.0 if ok else 0.0,
            metadata={
                "relationships_queried": rel_queried,
                "tables_named": named,
                "all_tables_named": all_named,
                "keys_named": keys_named,
            },
        )


class AnswerQueryRanWhenExpected(Scorer):
    """Binary: did a real (non-discovery) ``execute-sql`` answer query run?

    Gates the reused ``AnswerQueryRan`` behind an ``expected`` opt-in. The base
    scorer scores 0.0 even when the agent legitimately answers from
    ``information_schema`` alone, which would wrongly fail discovery/search cases —
    so this returns ``None`` unless the case opts in.
    """

    def __init__(self, *, name: str = "answer_query_ran") -> None:
        self._label = name

    def _name(self) -> str:
        return self._label

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _evaluate(self, output: dict | None, expected: dict | None = None) -> Score:
        if not output:
            return Score(name=self._name(), score=None, metadata={"reason": "No output"})
        if not _requested(expected, self._name()):
            return Score(name=self._name(), score=None, metadata={"reason": "not requested"})
        ran = extract_last_execute_sql_call(output) is not None
        return Score(name=self._name(), score=1.0 if ran else 0.0, metadata={"answer_query_ran": ran})


WAREHOUSE_ANSWER_PROMPT = """
You are an expert data analyst judging whether an agent correctly answered a user's question about a data warehouse, given the SQL it ran and its final message.

The agent navigates the warehouse via `system.information_schema` and `execute-sql`. Judge the FINAL message against the expected answer. Use the executed query and result as supporting evidence.

Grade on faithfulness and completeness:
- Reward an answer that matches the expected answer's key facts (the right table/column/value/relationship).
- For "duck typing" questions, reward correctly recognizing that a column declared as `String` actually holds numeric or JSON content by INSPECTING the values, and penalize an answer that trusts the declared type without looking at the data.
- Penalize fabricated values not supported by the SQL result, or an answer that contradicts the result.
- If the executed result is genuinely empty or unavailable, only accept an answer that honestly reports that — do not reward invented values.

User prompt:
<user_prompt>
{{output.prompt}}
</user_prompt>

Expected answer:
<expected_answer>
{{expected.expected_answer}}
</expected_answer>

Executed HogQL (may be "(no row query executed)"):
<executed_query>
{{output.sql_query}}
</executed_query>

SQL result (may be "(unavailable)"):
<sql_result>
{{output.sql_result}}
</sql_result>

Final assistant message:
<final_message>
{{output.final_message}}
</final_message>
""".strip()


WAREHOUSE_ANSWER_RUBRIC = """
How would you rate the assistant's final answer against the expected answer? Choose one:
- perfect: States the expected answer's key facts (table/column/value/relationship) with no errors.
- near_perfect: Conveys the expected answer with only a minor omission or harmless extra detail.
- slightly_off: Mostly correct but misses a minor fact or is slightly imprecise.
- somewhat_misaligned: Partly correct but omits an important fact or is hard to act on.
- strongly_misaligned: Contradicts the expected answer, answers a different question, or trusts a declared type without inspecting the data when the question required it.
- useless: No meaningful answer, fabricated value, or impossible to evaluate.

Be strict about factual faithfulness. Do not reward a fluent answer that invents values not supported by the SQL result.
""".strip()


class WarehouseAnswerCorrectness(JudgedScorer):
    """Graded LLM judge: did the final message correctly answer the warehouse question?

    Used on the nuanced duck-typing / relationship cases where string-matching is
    too brittle. Self-skips (``None``) when not requested, or when the case sets
    ``requires_queryable`` and the retrieval needle is not queryable in this env.
    """

    def _prepare(self, output, expected) -> dict[str, Any] | Score:
        spec = expected.get(self._name()) if isinstance(expected, dict) else None
        if not isinstance(spec, dict) or not isinstance(spec.get("expected_answer"), str):
            return Score(name=self._name(), score=None, metadata={"reason": "not requested"})
        if spec.get("requires_queryable"):
            retrieval = _seed(output).get("retrieval_needle")
            if not (isinstance(retrieval, dict) and retrieval.get("queryable")):
                return Score(name=self._name(), score=None, metadata={"reason": "needle not queryable in this env"})

        parser = parser_for(output)
        final = parser.get_final_agent_message() if parser is not None else None
        if not isinstance(final, str) or not final.strip():
            return Score(name=self._name(), score=0.0, metadata={"reason": "no final message"})

        call = extract_last_execute_sql_call(output)
        return {
            "output": {
                "prompt": user_prompt(output),
                "sql_query": call["query"] if call else "(no row query executed)",
                "sql_result": _truncate_result_for_judge(call["result"]) if call else "(unavailable)",
                "final_message": final,
            },
            "expected": {"expected_answer": spec["expected_answer"]},
        }

    def __init__(self, **kwargs):
        super().__init__(
            name="warehouse_answer_correctness",
            prompt_template=WAREHOUSE_ANSWER_PROMPT + "\n\n" + WAREHOUSE_ANSWER_RUBRIC,
            choice_scores=GRADED_ALIGNMENT_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=512,
            **kwargs,
        )
