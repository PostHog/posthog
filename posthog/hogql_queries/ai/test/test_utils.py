from datetime import timedelta

from posthog.test.base import BaseTest

from django.test import override_settings
from django.utils import timezone

import orjson
from parameterized import parameterized

from posthog.schema import CohortPropertyFilter, EventPropertyFilter, HogQLPropertyFilter, PropertyOperator

from posthog.hogql_queries.ai.utils import (
    TaxonomyCacheMixin,
    filled_property_filters,
    merge_heavy_properties,
    parse_ai_property_value,
)


class TestTaxonomyUtils(BaseTest):
    def test_is_stale(self):
        class Mixin(TaxonomyCacheMixin):
            team = self.team

        date = timezone.now()

        mixin = Mixin()
        self.assertFalse(mixin._is_stale(last_refresh=date, lazy=False))
        self.assertFalse(mixin._is_stale(last_refresh=date, lazy=True))
        self.assertFalse(mixin._is_stale(last_refresh=date - timedelta(minutes=15), lazy=False))
        self.assertFalse(mixin._is_stale(last_refresh=date - timedelta(minutes=15), lazy=True))
        self.assertFalse(mixin._is_stale(last_refresh=date - timedelta(minutes=59), lazy=True))
        self.assertFalse(mixin._is_stale(last_refresh=date - timedelta(minutes=59), lazy=False))
        self.assertTrue(mixin._is_stale(last_refresh=date - timedelta(minutes=60), lazy=True))
        self.assertTrue(mixin._is_stale(last_refresh=date - timedelta(minutes=60), lazy=False))


class TestMergeHeavyProperties(BaseTest):
    def test_merges_heavy_columns_into_properties(self):
        props_json = orjson.dumps({"$ai_model": "gpt-4", "$browser": "Chrome"}).decode()
        heavy = {
            "input": '[{"role": "user", "content": "hello"}]',
            "output": '{"role": "assistant", "content": "hi"}',
            "output_choices": "",
            "input_state": "",
            "output_state": "",
            "tools": "",
        }
        result = merge_heavy_properties(props_json, heavy)
        self.assertEqual(result["$ai_model"], "gpt-4")
        self.assertEqual(result["$browser"], "Chrome")
        self.assertEqual(result["$ai_input"], [{"role": "user", "content": "hello"}])
        self.assertEqual(result["$ai_output"], {"role": "assistant", "content": "hi"})
        self.assertNotIn("$ai_output_choices", result)
        self.assertNotIn("$ai_tools", result)

    def test_skips_empty_heavy_columns(self):
        props_json = orjson.dumps({"$ai_model": "gpt-4"}).decode()
        heavy = {"input": "", "output": "", "output_choices": "", "input_state": "", "output_state": "", "tools": ""}
        result = merge_heavy_properties(props_json, heavy)
        self.assertEqual(result, {"$ai_model": "gpt-4"})

    def test_handles_empty_properties(self):
        result = merge_heavy_properties("", {"input": '"hello"'})
        self.assertEqual(result, {"$ai_input": "hello"})

    @parameterized.expand(
        [
            ("input", "$ai_input"),
            ("output", "$ai_output"),
            ("output_choices", "$ai_output_choices"),
            ("input_state", "$ai_input_state"),
            ("output_state", "$ai_output_state"),
            ("tools", "$ai_tools"),
        ]
    )
    def test_maps_each_column_to_correct_property(self, column_name, expected_prop):
        result = merge_heavy_properties("{}", {column_name: '"test_value"'})
        self.assertEqual(result[expected_prop], "test_value")

    @parameterized.expand(
        [
            ("None",),
            ("False",),
            ("{'not': 'json'}",),
        ]
    )
    def test_parse_ai_property_value_preserves_invalid_json_strings(self, value):
        self.assertEqual(parse_ai_property_value(value), value)

    def test_parse_ai_property_value_preserves_json_strings_inside_lists(self):
        value = '["true", "123", "null", "{\\"role\\":\\"user\\"}"]'

        self.assertEqual(parse_ai_property_value(value), ["true", "123", "null", '{"role":"user"}'])

    @override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=True)
    def test_merge_preserves_empty_properties_independently_of_events_schema(self):
        result = merge_heavy_properties('{"$browser":"","$ai_model":null}', {})

        self.assertEqual(result, {"$browser": "", "$ai_model": None})


class TestFilledPropertyFilters(BaseTest):
    @parameterized.expand(
        [
            ("no_value", EventPropertyFilter(key="$ai_span_name", operator=PropertyOperator.EXACT)),
            ("empty_list", EventPropertyFilter(key="$ai_span_name", operator=PropertyOperator.EXACT, value=[])),
            ("no_key", EventPropertyFilter(key="", operator=PropertyOperator.EXACT, value="chat")),
            ("hogql_without_expression", HogQLPropertyFilter(key="")),
        ]
    )
    def test_drops_unusable_filters(self, _name, prop):
        self.assertEqual(filled_property_filters([prop]), [])

    @parameterized.expand(
        [
            ("string_value", EventPropertyFilter(key="$ai_span_name", operator=PropertyOperator.EXACT, value="chat")),
            ("list_value", EventPropertyFilter(key="$ai_span_name", operator=PropertyOperator.EXACT, value=["chat"])),
            ("empty_string", EventPropertyFilter(key="$ai_span_name", operator=PropertyOperator.EXACT, value="")),
            (
                "empty_string_in_list",
                EventPropertyFilter(key="$ai_span_name", operator=PropertyOperator.EXACT, value=[""]),
            ),
            ("is_set", EventPropertyFilter(key="$ai_span_name", operator=PropertyOperator.IS_SET)),
            ("is_not_set", EventPropertyFilter(key="$ai_span_name", operator=PropertyOperator.IS_NOT_SET)),
            ("false_value", EventPropertyFilter(key="$ai_is_error", operator=PropertyOperator.EXACT, value=False)),
            ("zero_value", EventPropertyFilter(key="$ai_input_tokens", operator=PropertyOperator.EXACT, value=0)),
            ("hogql_expression", HogQLPropertyFilter(key="toFloat(properties.$ai_latency) > 5")),
            ("cohort", CohortPropertyFilter(value=42)),
        ]
    )
    def test_keeps_usable_filters(self, _name, prop):
        self.assertEqual(filled_property_filters([prop]), [prop])

    def test_returns_empty_list_when_there_are_no_filters(self):
        self.assertEqual(filled_property_filters(None), [])
