import json

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
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.property_metadata import PropertyMetadata
from posthog.hogql.transforms.clickhouse_property_resolution import (
    MAX_MATERIALIZED_LIKE_PATTERN_LENGTH,
    _is_json_verbatim,
    clickhouse_property_resolution,
)

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
