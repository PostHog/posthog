import json

import pytest

from django.test import SimpleTestCase

from hypothesis import (
    example,
    given,
    settings as hypothesis_settings,
    strategies as st,
)
from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.schema.events import EventsPersonSubTable, EventsTable
from posthog.hogql.printer import print_prepared_ast
from posthog.hogql.property_metadata import PropertyMetadata
from posthog.hogql.transforms.clickhouse_property_resolution import (
    MAX_MATERIALIZED_LIKE_PATTERN_LENGTH,
    _is_json_verbatim,
    clickhouse_property_resolution,
)

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.events_json import TEMPORARY_PROPERTIES_JSON_TYPE
from posthog.models.event.sql import EVENTS_PROPERTIES_JSON_TYPE, PERSON_PROPERTIES_JSON_TYPE

from ee.clickhouse.materialized_columns.columns import MaterializedColumn, MaterializedColumnDetails

# Plain text alone almost never lands in the accepted set, so bias half the draws to printable ASCII.
_PROPERTY_VALUES = st.one_of(
    st.text(),
    st.text(alphabet=st.characters(min_codepoint=0x20, max_codepoint=0x7E)),
)


class TestJSONVerbatimValues(SimpleTestCase):
    # Producers differ on `ensure_ascii`, and the pre-check runs against whichever one wrote the blob.
    @given(value=_PROPERTY_VALUES)
    @example('some"thing')
    @example("back\\slash")
    @example("sömething")
    @example("tab\there")
    @example("plain_value-1")
    @hypothesis_settings(max_examples=100, deadline=None)
    def test_accepted_values_survive_json_encoding(self, value: str) -> None:
        if not _is_json_verbatim(value):
            return
        assert value in json.dumps({"key": value})
        assert value in json.dumps({"key": value}, ensure_ascii=False)


class TestMaterializedLikePatternLimit(SimpleTestCase):
    @parameterized.expand(
        [(op, oversized) for op in ("Like", "NotLike", "ILike", "NotILike") for oversized in (False, True)]
    )
    def test_pattern_limit_preserves_property_read(self, op: str, oversized: bool) -> None:
        column = MaterializedColumn(
            name="mat_label",
            details=MaterializedColumnDetails(table_column="properties", property_name="label", is_disabled=False),
            is_nullable=False,
        )
        context = HogQLContext(
            use_new_events_schema=False,
            property_metadata=PropertyMetadata(
                materialized_columns=lambda: {"events": {("label", "properties"): column}}
            ),
        )
        field_type = ast.FieldType(name="properties", table_type=ast.TableType(table=EventsTable()))
        pattern = "z" * (MAX_MATERIALIZED_LIKE_PATTERN_LENGTH + int(oversized))
        comparison = ast.CompareOperation(
            op=ast.CompareOperationOp[op],
            left=ast.PropertyAccess(expr=ast.Field(chain=["properties"], type=field_type), keys=["label"]),
            right=ast.Constant(value=pattern),
        )

        result: ast.Expr = clickhouse_property_resolution(comparison, context)

        if oversized:
            assert isinstance(result, ast.CompareOperation)
            assert result.op == comparison.op
            assert result.right == ast.Constant(value=pattern)
            assert isinstance(result.left, ast.Call)
            assert result.left.name == "nullIf"
        else:
            assert isinstance(result, ast.Call)
            assert result.name == {"Like": "like", "NotLike": "notLike", "ILike": "ilike", "NotILike": "notILike"}[op]
            assert isinstance(result.args[0], ast.Field)
            assert result.args[0].chain[-1] == "mat_label"


@pytest.mark.usefixtures("clickhouse_database")
class TestNativeJSONPropertyComparisons(SimpleTestCase):
    @parameterized.expand(
        [
            ("event", "properties", "value", "properties", "JSON", False),
            ("person", "person_properties", "value", "person_properties", PERSON_PROPERTIES_JSON_TYPE(), False),
            ("temporary", "properties", "$set", "temporary_properties", TEMPORARY_PROPERTIES_JSON_TYPE, False),
            ("dotted", "properties", "value.name", "properties", "JSON", False),
            ("declared_event", "properties", "$browser", "properties", EVENTS_PROPERTIES_JSON_TYPE(), True),
            (
                "declared_person",
                "person_properties",
                "$initial_browser",
                "person_properties",
                PERSON_PROPERTIES_JSON_TYPE(),
                True,
            ),
            (
                "person_event_key",
                "person_properties",
                "$session_id",
                "person_properties",
                PERSON_PROPERTIES_JSON_TYPE(),
                False,
            ),
        ]
    )
    def test_string_comparisons_preserve_mixed_values(
        self, _name: str, field: str, key: str, column: str, json_type: str, declared: bool
    ) -> None:
        context = HogQLContext(use_new_events_schema=True, property_metadata=PropertyMetadata())
        table_type = ast.TableAliasType(alias="events", table_type=ast.TableType(table=EventsTable()))
        field_type = ast.FieldType(name="properties", table_type=table_type)
        if field == "person_properties":
            field_type.table_type = ast.VirtualTableType(
                table_type=table_type, field="poe", virtual_table=EventsPersonSubTable()
            )
        prop = ast.PropertyAccess(
            expr=ast.Field(chain=[field], type=field_type), keys=[key], type=ast.StringType(nullable=True)
        )
        value = ast.Constant(value="5", type=ast.StringType(nullable=False))
        values = ast.Tuple(exprs=[value, ast.Constant(value="true", type=ast.StringType(nullable=False))])
        is_in = ast.CompareOperation(op=ast.CompareOperationOp.In, left=prop, right=values)
        expression = ast.Tuple(
            exprs=[
                ast.CompareOperation(op=ast.CompareOperationOp.Eq, left=prop, right=value),
                ast.CompareOperation(op=ast.CompareOperationOp.Eq, left=value, right=prop),
                ast.CompareOperation(op=ast.CompareOperationOp.NotEq, left=prop, right=value),
                is_in,
                ast.CompareOperation(op=ast.CompareOperationOp.NotIn, left=prop, right=values),
                ast.Not(expr=is_in),
            ]
        )
        lowered = clickhouse_property_resolution(expression, context)
        printed = print_prepared_ast(lowered, context, "clickhouse")
        assert "toJSONString" not in printed
        assert ("CAST(" in printed) is not declared
        read = print_prepared_ast(clickhouse_property_resolution(prop, context), context, "clickhouse")
        assert "JSONStripEmptyStringsAndNulls" not in read
        fallback_values = ["", "[5]", '{"child":""}']
        fallback = ast.Tuple(
            exprs=[
                ast.CompareOperation(op=ast.CompareOperationOp.Eq, left=prop, right=ast.Constant(value=value))
                for value in fallback_values
            ]
        )
        fallback_sql = print_prepared_ast(clickhouse_property_resolution(fallback, context), context, "clickhouse")

        cases: list[tuple[dict[str, object], int, int]] = [
            ({key: "5"}, 1, 1),
            ({key: 5}, 1, 1),
            ({key: True}, 0, 1),
            ({key: "05"}, 0, 0),
            ({key: "abc"}, 0, 0),
            ({key: "null"}, 0, 0),
            ({key: ""}, 0, 0),
            ({key: None}, 0, 0),
            ({}, 0, 0),
        ]
        if not declared:
            cases.extend(
                ({key: item}, 0, 0)
                for item in (
                    [],
                    {},
                    [5],
                    {"child": ""},
                    {"escaped": '\u0001"\\\t', "url": "https://example.com/path", "number": 2**63},
                    "[5]",
                    1.5,
                )
            )
        rows = sync_execute(
            f"SELECT {printed}, {read}, {fallback_sql} FROM (SELECT CAST(arrayJoin(%(documents)s), %(json_type)s) AS {column}) AS events",
            {**context.values, "documents": [json.dumps(doc) for doc, _, _ in cases], "json_type": json_type},
            settings={
                "transform_null_in": 1,
                "json_type_escape_dots_in_keys": 1,
                "output_format_json_escape_forward_slashes": 0,
            },
        )
        assert [row[0] for row in rows] == [(eq, eq, 1 - eq, member, 1 - member, 1 - member) for _, eq, member in cases]
        for (_, read_value, fallback_result), (document, _, _) in zip(rows, cases):
            assert fallback_result == tuple(int(read_value == value) for value in fallback_values)
            sent = document.get(key)
            if sent in (None, "", [], {}):
                assert read_value is None
            elif isinstance(sent, (list, dict)):
                assert json.loads(read_value) == sent
            else:
                assert read_value == ("true" if sent is True else str(sent))
