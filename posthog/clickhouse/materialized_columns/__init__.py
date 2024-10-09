from posthog.clickhouse.kafka_engine import trim_quotes_expr
from posthog.settings import EE_AVAILABLE
from typing import Any, NamedTuple


class MaterializedColumnInfo(NamedTuple):
    column_name: str
    is_nullable: bool

    @property
    def column_type(self) -> str:
        type_name = "String"
        if self.is_nullable:
            type_name = f"Nullable({type_name})"
        return type_name

    def get_expression_template(self, source_column: str, property_name: str) -> tuple[str, dict[str, Any]]:
        """
        Returns an expression and query parameter mapping that can be used to extract the property value from the source
        column.
        """
        property_parameter_name = "property_name"
        if self.is_nullable:
            extract_type_parameter_name = "column_type"
            return (
                f"JSONExtract({source_column}, %({property_parameter_name})s, %({extract_type_parameter_name})s)",
                {property_parameter_name: property_name, extract_type_parameter_name: self.column_type},
            )
        else:
            return trim_quotes_expr(f"JSONExtractRaw({source_column}, %({property_parameter_name})s)"), {
                property_parameter_name: property_name,
            }


if EE_AVAILABLE:
    from ee.clickhouse.materialized_columns.columns import *
else:
    from .column import *
