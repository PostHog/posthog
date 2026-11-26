import dataclasses
from typing import TYPE_CHECKING, Annotated, Any

import orjson
from pydantic import BaseModel, BeforeValidator, ConfigDict, InstanceOf

from posthog.schema import HogQLFilters, HogQLQueryModifiers, HogQLVariable

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
from posthog.hogql.context import HogQLContext
from posthog.hogql.json_ast import _deserialize_node, serialize_ast
from posthog.hogql.property_access_types import RestrictedProperty

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.workload import Workload

if TYPE_CHECKING:
    from posthog.models import User

_SelectFromWire = Annotated[
    InstanceOf[ast.SelectQuery] | InstanceOf[ast.SelectSetQuery], BeforeValidator(_deserialize_node)
]
_ExprFromWire = Annotated[InstanceOf[ast.Expr], BeforeValidator(_deserialize_node)]

_CONTEXT_FIELDS_THE_SERVICE_OWNS = frozenset(
    {
        "team_id",
        "team",
        "user",
        "user_access_control",
        "database",
        "timings",
        "values",
        "external_tables",
        "top_level_settings",
        "warnings",
        "notices",
        "errors",
        "data_warehouse_sync_warnings",
        "referenced_saved_query_ids",
        "materialized_saved_query_ids",
        "referenced_warehouse_table_ids",
        "directly_read_ids",
        "access_control_restricted_resources",
        "information_schema_introspection",
        "system_integrations_rows",
        "restricted_property_definition_ids",
        "cte_database_table_cache",
        "flag_call_property_metadata",
        "flag_called_union_spans",
        "flag_calls_read",
        "postgres_retention_starts",
        "_flag_calls_now",
        "holds_join_filters",
    }
)
_DEFAULT_CONTEXT = HogQLContext()


def _passed_fields(model: BaseModel) -> dict[str, Any]:
    return {name: getattr(model, name) for name in model.model_fields_set}


class ExecuteContext(BaseModel):
    model_config = ConfigDict(extra="forbid", defer_build=True)

    bypass_warehouse_access_control: bool | None = None
    use_new_events_schema: bool | None = None
    enable_select_queries: bool | None = None
    limit_top_select: bool | None = None
    limit_context: LimitContext | None = None
    globals: dict[str, Any] | None = None
    property_type_overrides: dict[str, str] | None = None
    restricted_properties: set[RestrictedProperty] | None = None
    modifiers: HogQLQueryModifiers | None = None
    apply_events_retention_floor: bool | None = None
    rewrite_flag_calls_to_flag_evaluations: bool | None = None
    order_events_reads_by_sort_key: bool | None = None

    @classmethod
    def from_context(cls, context: HogQLContext) -> "ExecuteContext":
        return cls(
            **{
                field.name: value
                for field in dataclasses.fields(context)
                if field.name not in _CONTEXT_FIELDS_THE_SERVICE_OWNS
                and (value := getattr(context, field.name)) != getattr(_DEFAULT_CONTEXT, field.name)
            }
        )

    def to_context(self, team_id: int, user: "User | None") -> HogQLContext:
        return HogQLContext(team_id=team_id, user=user, **_passed_fields(self))


class ExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", defer_build=True)

    query: str | _SelectFromWire | None
    context: ExecuteContext | None = None
    query_type: str | None = None
    filters: HogQLFilters | None = None
    placeholders: dict[str, _ExprFromWire] | None = None
    variables: dict[str, HogQLVariable] | None = None
    workload: Workload | None = None
    ch_user: ClickHouseUser | None = None
    settings: HogQLGlobalSettings | None = None
    modifiers: HogQLQueryModifiers | None = None
    limit_context: LimitContext | None = None
    pretty: bool | None = None
    connection_id: str | None = None
    expected_direct_engine: str | None = None
    trino_canary: bool | None = None
    send_raw_query: bool | None = None
    bypass_warehouse_access_control: bool | None = None
    refresh_stale_view_columns: bool | None = None
    returned_row_limit: int | None = None

    @classmethod
    def from_call(
        cls,
        query: str | ast.SelectQuery | ast.SelectSetQuery | None,
        *,
        context: HogQLContext | None = None,
        **arguments: Any,
    ) -> "ExecuteRequest":
        if context is not None:
            arguments["context"] = ExecuteContext.from_context(context)
        return cls(query=query, **arguments)

    def to_json(self) -> str:
        return orjson.dumps(_passed_fields(self), default=_to_wire, option=orjson.OPT_PASSTHROUGH_DATACLASS).decode()

    def executor_arguments(self) -> dict[str, Any]:
        return {name: value for name, value in _passed_fields(self).items() if name not in ("query", "context")}


def _to_wire(value: Any) -> Any:
    if isinstance(value, ast.AST):
        return orjson.Fragment(serialize_ast(value))
    if isinstance(value, BaseModel):
        return orjson.Fragment(value.model_dump_json(include=value.model_fields_set))
    raise TypeError(f"Cannot send a value of type {type(value).__name__}")
