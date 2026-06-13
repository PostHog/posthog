import json
from typing import Any

from unittest import TestCase

from parameterized import parameterized

from ee.hogai.core.ai_event_truncation import (
    AI_EVENT_TRUNCATED_COUNTER,
    COMBINED_EVENT_CEILING,
    PER_BLOB_BYTE_BUDGET,
    TRUNCATED_FLAG_PROP,
    TRUNCATION_MARKER,
    AIEventTruncator,
    ai_event_truncator,
    byte_size,
)

SDK_EVENT_DROP_BYTES = 900 * 1024


def _counter_value(event: str, prop: str, tier: str) -> float:
    return AI_EVENT_TRUNCATED_COUNTER.labels(event=event, property=prop, tier=tier)._value.get()


class TestTruncateBlob(TestCase):
    def setUp(self):
        self.truncator = AIEventTruncator()

    def test_under_budget_is_noop_and_returns_same_object(self):
        state = {"messages": [{"type": "human", "content": "hi"}], "graph_status": ""}
        result, tier = self.truncator.truncate_blob(state, byte_budget=10_000)
        self.assertIsNone(tier)
        self.assertIs(result, state)

    def test_leaf_truncation_caps_long_strings_and_keeps_structure(self):
        state = {"messages": [{"type": "ai", "content": "x" * 50_000, "id": "abc"}]}
        result, tier = AIEventTruncator(per_string_cap=200).truncate_blob(state, byte_budget=2_000)
        self.assertEqual(tier, "leaf")
        self.assertLessEqual(byte_size(result), 2_000)
        message = result["messages"][0]
        self.assertEqual(message["type"], "ai")
        self.assertEqual(message["id"], "abc")
        self.assertTrue(message["content"].endswith(TRUNCATION_MARKER))

    def test_strip_drops_content_but_preserves_billing_fields(self):
        state = {
            "messages": [
                {"type": "human", "content": "q" * 60_000},
                {
                    "type": "ai",
                    "content": "a" * 60_000,
                    "tool_calls": [
                        {"name": "search", "id": "t1", "args": {"kind": "docs", "query": "z" * 60_000}},
                        {"name": "create_insight", "id": "t2", "args": {"spec": "y" * 60_000}},
                    ],
                },
            ],
            "intermediate": "k" * 60_000,
        }
        result, tier = self.truncator.truncate_blob(state, byte_budget=2_000)
        self.assertEqual(tier, "strip")
        self.assertLessEqual(byte_size(result), 2_000)
        # Billing reads top-level messages → type, tool_calls.name, and args.kind for search.
        types = [m["type"] for m in result["messages"]]
        self.assertEqual(types, ["human", "ai"])
        tool_calls = result["messages"][1]["tool_calls"]
        self.assertEqual(tool_calls[0]["name"], "search")
        self.assertEqual(tool_calls[0]["args"]["kind"], "docs")
        self.assertEqual(tool_calls[1]["name"], "create_insight")
        # Non-search args are dropped (billing never reads them); heavy content is gone.
        self.assertNotIn("args", tool_calls[1])
        self.assertNotIn("content", result["messages"][1])
        self.assertNotIn("intermediate", result)

    def test_front_trim_keeps_tail_and_bounds_size(self):
        messages = [{"type": "tool", "tool_call_id": str(i)} for i in range(2_000)]
        state = {"messages": messages}
        result, tier = self.truncator.truncate_blob(state, byte_budget=1_500)
        self.assertEqual(tier, "trim")
        self.assertLessEqual(byte_size(result), 1_500)
        kept = result["messages"]
        self.assertGreaterEqual(len(kept), 1)
        self.assertLess(len(kept), 2_000)
        # The kept messages are a suffix (tail) of the original — billing reads the current turn.
        self.assertEqual(kept, messages[-len(kept) :])

    def test_bare_list_of_messages_is_truncated(self):
        choices = [{"role": "assistant", "content": "c" * 60_000, "tool_calls": [{"name": "x", "args": {}}]}]
        result, tier = AIEventTruncator(per_string_cap=200).truncate_blob(choices, byte_budget=2_000)
        self.assertEqual(tier, "leaf")
        self.assertLessEqual(byte_size(result), 2_000)
        self.assertEqual(result[0]["role"], "assistant")

    def test_bare_list_strip_preserves_role(self):
        choices = [{"role": "assistant", "content": "c" * 60_000} for _ in range(3)]
        result, tier = self.truncator.truncate_blob(choices, byte_budget=300)
        self.assertEqual(tier, "strip")
        self.assertLessEqual(byte_size(result), 300)
        self.assertTrue(all(m["role"] == "assistant" for m in result))
        self.assertTrue(all("content" not in m for m in result))

    def test_nested_messages_are_found_and_flattened(self):
        state = {"agent": {"messages": [{"type": "ai", "content": "z" * 60_000}]}}
        result, tier = self.truncator.truncate_blob(state, byte_budget=2_000)
        self.assertEqual(tier, "strip")
        # Re-emitted at top-level "messages" where billing reads it.
        self.assertIn("messages", result)
        self.assertEqual(result["messages"][0]["type"], "ai")

    def test_scalar_without_messages_hits_hard_fallback(self):
        result, tier = self.truncator.truncate_blob("s" * 50_000, byte_budget=1_000)
        self.assertEqual(tier, "hard")
        self.assertLessEqual(byte_size(result), 1_000)
        self.assertTrue(result[TRUNCATED_FLAG_PROP])

    def test_dict_without_messages_hits_hard_fallback(self):
        state = {"blob": "b" * 50_000, "more": "m" * 50_000}
        result, tier = AIEventTruncator(per_string_cap=40_000).truncate_blob(state, byte_budget=1_000)
        self.assertEqual(tier, "hard")
        self.assertLessEqual(byte_size(result), 1_000)

    def test_single_oversized_tail_message_still_bounded(self):
        # One message whose billing fields alone (thousands of tool_calls) blow the budget.
        # Strip can't help, front-trim can't drop the only message, so the hard fallback must bound it.
        huge = [{"type": "ai", "tool_calls": [{"name": "search", "id": str(i)} for i in range(5_000)]}]
        for value in ({"messages": huge}, list(huge)):
            result, tier = self.truncator.truncate_blob(value, byte_budget=2_000)
            self.assertEqual(tier, "trim")
            self.assertLessEqual(byte_size(result), 2_000)
            json.dumps(result)  # must not raise

    @parameterized.expand(
        [
            ("dict_messages", {"messages": [{"type": "ai", "content": "x" * 80_000}]}),
            ("bare_list", [{"role": "assistant", "content": "x" * 80_000}]),
            ("scalar", "x" * 80_000),
            ("nested", {"a": {"messages": [{"type": "tool", "content": "x" * 80_000}]}}),
        ]
    )
    def test_result_is_valid_json_and_within_budget(self, _name, value):
        result, tier = self.truncator.truncate_blob(value, byte_budget=2_000)
        self.assertIsNotNone(tier)
        self.assertLessEqual(byte_size(result), 2_000)
        json.dumps(result)  # must not raise


class TestTruncateAiEvent(TestCase):
    def test_non_ai_event_is_untouched(self):
        msg = {"event": "$pageview", "properties": {"$ai_input_state": "x" * 2_000_000}}
        result = ai_event_truncator(msg)
        self.assertEqual(len(result["properties"]["$ai_input_state"]), 2_000_000)
        self.assertNotIn(TRUNCATED_FLAG_PROP, result["properties"])

    def test_malformed_input_never_raises(self):
        self.assertEqual(ai_event_truncator({"event": "$ai_trace"}), {"event": "$ai_trace"})
        self.assertEqual(
            ai_event_truncator({"event": "$ai_trace", "properties": None}), {"event": "$ai_trace", "properties": None}
        )

    @parameterized.expand(
        [
            ("$ai_trace", "$ai_output_state"),
            ("$ai_span", "$ai_input_state"),
            ("$ai_generation", "$ai_input"),
            ("$ai_generation", "$ai_output_choices"),
        ]
    )
    def test_oversized_property_is_truncated_under_budget(self, event, prop):
        before = _counter_value(event, prop, "leaf")
        msg = {
            "event": event,
            "properties": {prop: {"messages": [{"type": "ai", "content": "x" * (PER_BLOB_BYTE_BUDGET + 50_000)}]}},
        }
        result = ai_event_truncator(msg)
        self.assertLessEqual(byte_size(result["properties"][prop]), PER_BLOB_BYTE_BUDGET)
        self.assertTrue(result["properties"][TRUNCATED_FLAG_PROP])
        self.assertEqual(_counter_value(event, prop, "leaf"), before + 1)

    def test_combined_ceiling_keeps_event_under_sdk_drop(self):
        # Two blobs each under the per-blob budget but together over the combined ceiling.
        def blob() -> dict:
            return {"messages": [{"type": "ai", "content": "x" * 500} for _ in range(1_300)]}

        msg: dict[str, Any] = {
            "event": "$ai_trace",
            "properties": {"$ai_input_state": blob(), "$ai_output_state": blob()},
        }
        self.assertGreater(
            byte_size(msg["properties"]["$ai_input_state"]) + byte_size(msg["properties"]["$ai_output_state"]),
            COMBINED_EVENT_CEILING,
        )
        result = ai_event_truncator(msg)
        combined = byte_size(result["properties"]["$ai_input_state"]) + byte_size(
            result["properties"]["$ai_output_state"]
        )
        self.assertLessEqual(combined, COMBINED_EVENT_CEILING)
        self.assertLess(byte_size(result), SDK_EVENT_DROP_BYTES)
        self.assertTrue(result["properties"][TRUNCATED_FLAG_PROP])

    def test_under_budget_event_is_unchanged(self):
        msg = {
            "event": "$ai_generation",
            "properties": {
                "$ai_input": [{"role": "user", "content": "hi"}],
                "$ai_input_tokens": 10,
                "$ai_total_cost_usd": "0.01",
            },
        }
        result = ai_event_truncator(msg)
        self.assertEqual(result["properties"]["$ai_input"], [{"role": "user", "content": "hi"}])
        self.assertNotIn(TRUNCATED_FLAG_PROP, result["properties"])

    def test_token_and_cost_properties_are_never_touched(self):
        msg = {
            "event": "$ai_generation",
            "properties": {
                "$ai_input": [{"role": "user", "content": "x" * (PER_BLOB_BYTE_BUDGET + 50_000)}],
                "$ai_input_tokens": 1234,
                "$ai_output_tokens": 567,
                "$ai_total_cost_usd": "0.42",
                "$ai_billable": True,
            },
        }
        result = ai_event_truncator(msg)
        self.assertEqual(result["properties"]["$ai_input_tokens"], 1234)
        self.assertEqual(result["properties"]["$ai_output_tokens"], 567)
        self.assertEqual(result["properties"]["$ai_total_cost_usd"], "0.42")
        self.assertTrue(result["properties"]["$ai_billable"])
