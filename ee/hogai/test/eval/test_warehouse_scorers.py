"""Unit tests for the data-warehouse information_schema scorers.

Builds minimal ACP session logs (the same shape ``LogParser`` consumes in
production) plus synthetic ``seed`` dicts, then asserts each scorer's verdict —
no sandboxed stack. Lives above ``sandboxed/`` so it stays a fast unit test
instead of booting the eval harness via that package's conftest.
"""

from __future__ import annotations

import json

from braintrust import Score

from ee.hogai.eval.sandboxed.data_warehouse.scorers import (
    AgenticSearchUsed,
    AnswerQueryRanWhenExpected,
    InformationSchemaBeforeAnswer,
    InformationSchemaQueried,
    JoinPathTraversed,
    NeedleTableIdentified,
    NeedleValueRetrieved,
    RelationshipDiscovery,
    StaleTableAvoided,
    WarehouseAnswerCorrectness,
)

_TS = "2026-04-15T10:00:0"


def _session_update(seq: int, update: dict) -> str:
    return json.dumps(
        {
            "type": "notification",
            "timestamp": f"{_TS}{seq}.000Z",
            "notification": {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {"sessionId": "s", "update": update},
            },
        }
    )


def _prompt(seq: int, text: str) -> str:
    return json.dumps(
        {
            "type": "notification",
            "timestamp": f"{_TS}{seq}.000Z",
            "notification": {
                "jsonrpc": "2.0",
                "method": "session/prompt",
                "params": {"sessionId": "s", "prompt": [{"type": "text", "text": text}]},
            },
        }
    )


def _end_turn(seq: int) -> str:
    return json.dumps(
        {
            "type": "notification",
            "timestamp": f"{_TS}{seq}.000Z",
            "notification": {
                "jsonrpc": "2.0",
                "result": {
                    "stopReason": "end_turn",
                    "usage": {
                        "inputTokens": 1,
                        "outputTokens": 1,
                        "cachedReadTokens": 0,
                        "cachedWriteTokens": 0,
                        "totalTokens": 2,
                    },
                },
            },
        }
    )


def _sql_call(seq: int, call_id: str, query: str, output: str = "ok", status: str = "completed") -> list[str]:
    return [
        _session_update(
            seq,
            {
                "sessionUpdate": "tool_call",
                "toolCallId": call_id,
                "status": "pending",
                "rawInput": {},
                "title": "execute-sql",
                "_meta": {"claudeCode": {"toolName": "execute-sql"}},
            },
        ),
        _session_update(
            seq,
            {"sessionUpdate": "tool_call_update", "toolCallId": call_id, "status": None, "rawInput": {"query": query}},
        ),
        _session_update(
            seq,
            {"sessionUpdate": "tool_call_update", "toolCallId": call_id, "status": status, "rawOutput": output},
        ),
    ]


def _agent_text(seq: int, text: str) -> str:
    return _session_update(seq, {"sessionUpdate": "agent_message", "content": {"type": "text", "text": text}})


def _make_output(
    *,
    sql_calls: list[tuple[str, str]] | None = None,  # (query, result)
    final_text: str = "done",
    seed: dict | None = None,
) -> dict:
    lines = [_prompt(0, "question")]
    seq = 1
    for idx, (query, result) in enumerate(sql_calls or []):
        lines.extend(_sql_call(seq, f"c{idx}", query, output=result))
        seq += 1
    lines.append(_agent_text(seq, final_text))
    lines.append(_end_turn(seq + 1))
    return {
        "raw_log": "\n".join(lines),
        "last_message": final_text,
        "prompt": "question",
        "seed": seed or {},
    }


# -- InformationSchemaQueried -------------------------------------------------


def test_information_schema_queried_passes_when_info_schema_hit():
    out = _make_output(sql_calls=[("SELECT table_name FROM system.information_schema.tables", "rows")])
    score = InformationSchemaQueried()._evaluate(out, {"information_schema_queried": {}})
    assert score.score == 1.0


def test_information_schema_queried_fails_without_info_schema():
    out = _make_output(sql_calls=[("SELECT 1 FROM stripe_charges", "rows")])
    score = InformationSchemaQueried()._evaluate(out, {"information_schema_queried": {}})
    assert score.score == 0.0


def test_information_schema_queried_skips_when_not_requested():
    out = _make_output(sql_calls=[("SELECT 1 FROM system.information_schema.tables", "rows")])
    score = InformationSchemaQueried()._evaluate(out, {})
    assert score.score is None


# -- InformationSchemaBeforeAnswer --------------------------------------------


def test_before_answer_passes_when_discovery_precedes_answer():
    out = _make_output(
        sql_calls=[
            ("SELECT column_name FROM system.information_schema.columns WHERE table_name = 'pg_orders'", "rows"),
            ("SELECT * FROM pg_orders LIMIT 5", "rows"),
        ]
    )
    score = InformationSchemaBeforeAnswer()._evaluate(out, {"information_schema_before_answer": {}})
    assert score.score == 1.0


def test_before_answer_fails_when_answer_precedes_discovery():
    out = _make_output(
        sql_calls=[
            ("SELECT * FROM pg_orders LIMIT 5", "rows"),
            ("SELECT column_name FROM system.information_schema.columns", "rows"),
        ]
    )
    score = InformationSchemaBeforeAnswer()._evaluate(out, {"information_schema_before_answer": {}})
    assert score.score == 0.0


def test_before_answer_skips_when_no_answer_query():
    out = _make_output(sql_calls=[("SELECT table_name FROM system.information_schema.tables", "rows")])
    score = InformationSchemaBeforeAnswer()._evaluate(out, {"information_schema_before_answer": {}})
    assert score.score is None


# -- AgenticSearchUsed --------------------------------------------------------


def test_agentic_search_passes_for_filtered_query():
    out = _make_output(
        sql_calls=[("SELECT table_name FROM system.information_schema.tables WHERE table_name = 'pg_orders'", "rows")]
    )
    score = AgenticSearchUsed()._evaluate(out, {"agentic_search_used": {}})
    assert score.score == 1.0


def test_agentic_search_fails_for_unfiltered_dump():
    out = _make_output(sql_calls=[("SELECT table_name FROM system.information_schema.tables", "rows")])
    score = AgenticSearchUsed()._evaluate(out, {"agentic_search_used": {}})
    assert score.score == 0.0


def test_agentic_search_require_pattern_needs_like():
    where_eq = _make_output(
        sql_calls=[("SELECT table_name FROM system.information_schema.tables WHERE table_name = 'x'", "rows")]
    )
    where_like = _make_output(
        sql_calls=[("SELECT table_name FROM system.information_schema.tables WHERE description ILIKE '%mrr%'", "rows")]
    )
    spec = {"agentic_search_used": {"require_pattern": True}}
    assert AgenticSearchUsed()._evaluate(where_eq, spec).score == 0.0
    assert AgenticSearchUsed()._evaluate(where_like, spec).score == 1.0


# -- NeedleTableIdentified ----------------------------------------------------


def test_needle_table_identified_via_final_message():
    out = _make_output(final_text="The canonical MRR table is pg_ext_4471.")
    score = NeedleTableIdentified()._evaluate(out, {"needle_table_identified": {"table": "pg_ext_4471"}})
    assert score.score == 1.0


def test_needle_table_identified_resolves_seed_key():
    out = _make_output(
        final_text="It's hubspot_sync_meta.", seed={"column_type_needle": {"table": "hubspot_sync_meta"}}
    )
    score = NeedleTableIdentified()._evaluate(out, {"needle_table_identified": {"seed_key": "column_type_needle"}})
    assert score.score == 1.0


def test_needle_table_identified_fails_when_absent():
    out = _make_output(final_text="I could not find it.")
    score = NeedleTableIdentified()._evaluate(out, {"needle_table_identified": {"table": "pg_ext_4471"}})
    assert score.score == 0.0


# -- NeedleValueRetrieved -----------------------------------------------------


def test_needle_value_retrieved_from_sql_result():
    out = _make_output(
        sql_calls=[("SELECT payload FROM evalwh_stripe_raw_events WHERE event_id = 'evt_target'", "HEDGE-7731")],
        final_text="The secret_code is HEDGE-7731.",
        seed={"retrieval_needle": {"queryable": True, "answer": "HEDGE-7731"}},
    )
    score = NeedleValueRetrieved()._evaluate(out, {"needle_value_retrieved": {}})
    assert score.score == 1.0


def test_needle_value_retrieved_skips_when_not_queryable():
    out = _make_output(seed={"retrieval_needle": {"queryable": False, "answer": "HEDGE-7731"}})
    score = NeedleValueRetrieved()._evaluate(out, {"needle_value_retrieved": {}})
    assert score.score is None


def test_needle_value_retrieved_honors_value_override():
    out = _make_output(
        sql_calls=[("SELECT max(toInt64(amount)) FROM evalwh_stripe_raw_events", "24990")],
        final_text="Largest is 24990.",
        seed={"retrieval_needle": {"queryable": True, "answer": "HEDGE-7731"}},
    )
    score = NeedleValueRetrieved()._evaluate(out, {"needle_value_retrieved": {"value": "24990"}})
    assert score.score == 1.0


# -- RelationshipDiscovery ----------------------------------------------------


def test_relationship_discovery_passes_with_relationships_query_and_named_pair():
    out = _make_output(
        sql_calls=[
            ("SELECT * FROM system.information_schema.relationships WHERE source_table = 'pg_orders_2023'", "r")
        ],
        final_text="pg_orders_2023 joins salesforce_acct_xref on account_ref.",
        seed={"relationship_needle": {"source": "pg_orders_2023", "target": "salesforce_acct_xref"}},
    )
    score = RelationshipDiscovery()._evaluate(out, {"relationship_discovery": {}})
    assert score.score == 1.0


def test_relationship_discovery_fails_without_discovery():
    out = _make_output(
        final_text="They are probably related somehow.",
        seed={"relationship_needle": {"source": "pg_orders_2023", "target": "salesforce_acct_xref"}},
    )
    score = RelationshipDiscovery()._evaluate(out, {"relationship_discovery": {}})
    assert score.score == 0.0


# -- StaleTableAvoided --------------------------------------------------------

_RELEVANCY_SEED = {"relevancy_needle": {"current": "dim_accounts_snapshot", "stale": "dim_accounts_snapshot_2023"}}


def test_stale_table_avoided_passes_when_current_recommended_and_stale_flagged():
    out = _make_output(
        final_text=(
            "Use dim_accounts_snapshot — it's the live canonical table. "
            "dim_accounts_snapshot_2023 is deprecated and no longer refreshed."
        ),
        seed=_RELEVANCY_SEED,
    )
    score = StaleTableAvoided()._evaluate(out, {"stale_table_avoided": {}})
    assert score.score == 1.0


def test_stale_table_avoided_passes_when_only_current_named():
    out = _make_output(final_text="You should use dim_accounts_snapshot for current reporting.", seed=_RELEVANCY_SEED)
    score = StaleTableAvoided()._evaluate(out, {"stale_table_avoided": {}})
    assert score.score == 1.0


def test_stale_table_avoided_fails_when_stale_recommended():
    out = _make_output(final_text="Use dim_accounts_snapshot_2023 for your accounts reporting.", seed=_RELEVANCY_SEED)
    score = StaleTableAvoided()._evaluate(out, {"stale_table_avoided": {}})
    assert score.score == 0.0


def test_stale_table_avoided_fails_when_stale_named_without_deprecation_cue():
    # Both named but no cue flags the stale one — reads as offering it as usable.
    out = _make_output(
        final_text="There's dim_accounts_snapshot and dim_accounts_snapshot_2023; either has accounts.",
        seed=_RELEVANCY_SEED,
    )
    score = StaleTableAvoided()._evaluate(out, {"stale_table_avoided": {}})
    assert score.score == 0.0


def test_stale_table_avoided_skips_when_not_requested():
    out = _make_output(final_text="anything", seed=_RELEVANCY_SEED)
    score = StaleTableAvoided()._evaluate(out, {})
    assert score.score is None


# -- JoinPathTraversed --------------------------------------------------------

_CHAIN_SEED = {
    "chain_needle": {
        "tables": ["pg_orders_2023", "salesforce_acct_xref", "salesforce_acct_owners"],
        "keys": ["account_ref", "owner_id"],
    }
}


def test_join_path_traversed_passes_with_relationships_query_and_all_tables_named():
    out = _make_output(
        sql_calls=[
            ("SELECT * FROM system.information_schema.relationships WHERE source_table = 'pg_orders_2023'", "r"),
            ("SELECT * FROM system.information_schema.relationships WHERE source_table = 'salesforce_acct_xref'", "r"),
        ],
        final_text=(
            "Join pg_orders_2023 to salesforce_acct_xref on account_ref, then "
            "salesforce_acct_xref to salesforce_acct_owners on owner_id."
        ),
        seed=_CHAIN_SEED,
    )
    score = JoinPathTraversed()._evaluate(out, {"join_path_traversed": {}})
    assert score.score == 1.0
    assert score.metadata["keys_named"] == ["account_ref", "owner_id"]


def test_join_path_traversed_fails_when_only_first_hop_found():
    out = _make_output(
        sql_calls=[
            ("SELECT * FROM system.information_schema.relationships WHERE source_table = 'pg_orders_2023'", "r"),
        ],
        final_text="pg_orders_2023 joins salesforce_acct_xref on account_ref.",
        seed=_CHAIN_SEED,
    )
    score = JoinPathTraversed()._evaluate(out, {"join_path_traversed": {}})
    assert score.score == 0.0


def test_join_path_traversed_fails_without_relationships_query():
    out = _make_output(
        final_text="pg_orders_2023, salesforce_acct_xref and salesforce_acct_owners are probably related.",
        seed=_CHAIN_SEED,
    )
    score = JoinPathTraversed()._evaluate(out, {"join_path_traversed": {}})
    assert score.score == 0.0


def test_join_path_traversed_skips_when_not_requested():
    out = _make_output(final_text="anything", seed=_CHAIN_SEED)
    score = JoinPathTraversed()._evaluate(out, {})
    assert score.score is None


# -- AnswerQueryRanWhenExpected -----------------------------------------------


def test_answer_query_ran_true_for_real_answer():
    out = _make_output(sql_calls=[("SELECT * FROM pg_orders LIMIT 5", "rows")])
    score = AnswerQueryRanWhenExpected()._evaluate(out, {"answer_query_ran": {}})
    assert score.score == 1.0


def test_answer_query_ran_false_for_discovery_only():
    out = _make_output(sql_calls=[("SELECT table_name FROM system.information_schema.tables", "rows")])
    score = AnswerQueryRanWhenExpected()._evaluate(out, {"answer_query_ran": {}})
    assert score.score == 0.0


def test_answer_query_ran_skips_when_not_requested():
    out = _make_output(sql_calls=[("SELECT * FROM pg_orders", "rows")])
    score = AnswerQueryRanWhenExpected()._evaluate(out, {})
    assert score.score is None


# -- WarehouseAnswerCorrectness (synchronous short-circuits only) -------------


def test_warehouse_answer_correctness_skips_when_not_requested():
    out = _make_output(final_text="anything")
    prepared = WarehouseAnswerCorrectness()._prepare(out, {})
    assert isinstance(prepared, Score) and prepared.score is None


def test_warehouse_answer_correctness_skips_when_requires_queryable_unavailable():
    out = _make_output(final_text="anything", seed={"retrieval_needle": {"queryable": False}})
    spec = {"warehouse_answer_correctness": {"expected_answer": "x", "requires_queryable": True}}
    prepared = WarehouseAnswerCorrectness()._prepare(out, spec)
    assert isinstance(prepared, Score) and prepared.score is None
