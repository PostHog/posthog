from typing import TYPE_CHECKING, cast

from posthog.schema_enums import InCohortVia, PropertyGroupsMode

if TYPE_CHECKING:
    from posthog.schema import HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.constants import SQL_TARGET_DIALECTS, HogQLDialect, HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import InternalHogQLError
from posthog.hogql.modifiers import create_default_modifiers_for_team, set_default_in_cohort_via
from posthog.hogql.observability import (
    collect_hogql_sql_shape,
    collect_hogql_type_coverage,
    create_hogql_type_observability,
    emit_hogql_type_observability,
)
from posthog.hogql.printer.base import BasePrinter
from posthog.hogql.printer.clickhouse import ClickHousePrinter
from posthog.hogql.printer.duckdb import DuckDBPrinter
from posthog.hogql.printer.hogql import HogQLPrinter
from posthog.hogql.printer.mysql import MySQLPrinter
from posthog.hogql.printer.postgres import PostgresPrinter
from posthog.hogql.printer.snowflake import SnowflakePrinter
from posthog.hogql.resolver import ResolverFactory, resolve_types
from posthog.hogql.transforms.clickhouse_property_resolution import clickhouse_property_resolution
from posthog.hogql.transforms.events_predicate_pushdown import apply_events_predicate_pushdown, events_pushdown_enabled
from posthog.hogql.transforms.geoip_dict_fallback import (
    apply_geoip_dict_fallback_delete_this_function_when_inc_2026_06_11_maxmind_missing_data_is_resolved,
    geoip_dict_fallback_enabled_for_team,
)
from posthog.hogql.transforms.in_cohort import resolve_in_cohorts, resolve_in_cohorts_conjoined
from posthog.hogql.transforms.json_property_pushdown import (
    has_rewritable_json_extract,
    rewrite_json_extract_to_property,
)
from posthog.hogql.transforms.lazy_tables import resolve_lazy_tables
from posthog.hogql.transforms.logical_property_lowering import lower_property_access
from posthog.hogql.transforms.projection_pushdown import pushdown_projections
from posthog.hogql.transforms.property_types import PropertySwapper, build_property_swapper
from posthog.hogql.transforms.type_aware_simplification import (
    simplify_argmax_over_non_nullable,
    simplify_redundant_type_operations,
)
from posthog.hogql.visitor import clone_expr
from posthog.hogql.workload import WorkloadCollector

from posthog.clickhouse.workload import Workload
from posthog.models.team import Team
from posthog.models.team.event_retention import events_retention_months_for_team
from posthog.shared_link_viewer import SharedLinkViewer

from products.access_control.backend.property_access_control import get_restricted_properties_for_team

PRINTER_CLASSES: dict[HogQLDialect, type[BasePrinter]] = {
    "clickhouse": ClickHousePrinter,
    "postgres": PostgresPrinter,
    "duckdb": DuckDBPrinter,
    "mysql": MySQLPrinter,
    "snowflake": SnowflakePrinter,
    "hogql": HogQLPrinter,
}


def to_printed_hogql(
    query: ast.Expr,
    team: Team,
    modifiers: "HogQLQueryModifiers | None" = None,
    *,
    bypass_warehouse_access_control: bool = False,
) -> str:
    """Prints the HogQL query without mutating the node"""
    return prepare_and_print_ast(
        clone_expr(query),
        dialect="hogql",
        context=HogQLContext(
            team_id=team.pk,
            enable_select_queries=True,
            modifiers=create_default_modifiers_for_team(team, modifiers),
            bypass_warehouse_access_control=bypass_warehouse_access_control,
        ),
        pretty=True,
    )[0]


def prepare_and_print_ast(
    node: _T_AST,
    context: HogQLContext,
    dialect: HogQLDialect,
    stack: list[ast.SelectQuery] | None = None,
    settings: HogQLGlobalSettings | None = None,
    pretty: bool = False,
) -> tuple[str, _T_AST | None]:
    previous_type_observability = context.type_observability
    context.type_observability = create_hogql_type_observability(
        dialect=dialect,
        source=context.observability_source,
    )
    try:
        prepared_ast = prepare_ast_for_printing(
            node=node, context=context, dialect=dialect, stack=stack, settings=settings
        )
        if prepared_ast is None:
            if context.type_observability is not None:
                context.type_observability.result = "empty"
            return "", None

        collect_hogql_type_coverage(prepared_ast, context.type_observability, context)
        collect_hogql_sql_shape(prepared_ast, context.type_observability)

        printed = print_prepared_ast(
            node=prepared_ast,
            context=context,
            dialect=dialect,
            stack=stack,
            settings=settings,
            pretty=pretty,
        )
        return printed, prepared_ast
    except Exception:
        if context.type_observability is not None:
            context.type_observability.result = "error"
            context.type_observability.record_unknown("inference_exception")
        raise
    finally:
        emit_hogql_type_observability(context.type_observability)
        context.type_observability = previous_type_observability


def prepare_ast_for_printing(
    node: _T_AST,  # node is mutated
    context: HogQLContext,
    dialect: HogQLDialect,
    stack: list[ast.SelectQuery] | None = None,
    settings: HogQLGlobalSettings | None = None,
    resolver_factory: ResolverFactory | None = None,
) -> _T_AST | None:
    if context.database is None:
        with context.timings.measure("create_hogql_database"):  # Legacy name to keep backwards compatibility
            # Passing both `team_id` and `team` because `team` is not always available in the context
            context.database = Database.create_for(
                context.team_id,
                modifiers=context.modifiers,
                team=context.team,
                user=context.user,
                timings=context.timings,
                bypass_warehouse_access_control=context.bypass_warehouse_access_control,
            )
    if context.direct_postgres_connection_metadata is None and context.database is not None:
        context.direct_postgres_connection_metadata = getattr(context.database, "_direct_connection_metadata", None)

    context.modifiers = set_default_in_cohort_via(context.modifiers)

    # Load property-level access control restrictions onto the context. They are enforced only on the ClickHouse path —
    # the printer wraps the JSON blob in JSONDropKeys, and property resolution declines backing columns (and reads a
    # restricted property as NULL). The warehouse (Postgres / DuckDB) dialects only compile external data-warehouse
    # sources, which carry no restrictable event/person properties, so they need no enforcement here.
    if context.team_id is not None and context.restricted_properties is None:
        with context.timings.measure("load_restricted_properties"):
            # Shared-link viewer has no membership to resolve against; treat as userless so only default rules apply.
            restrictions_user = None if isinstance(context.user, SharedLinkViewer) else context.user
            context.restricted_properties = get_restricted_properties_for_team(
                team_id=context.team_id,
                user=restrictions_user,
            )

    if context.modifiers.inCohortVia == InCohortVia.LEFTJOIN_CONJOINED:
        with context.timings.measure("resolve_in_cohorts_conjoined"):
            resolve_in_cohorts_conjoined(node, dialect, context, stack, resolver_factory=resolver_factory)

    with context.timings.measure("resolve_types"):
        node = resolve_types(
            node,
            context,
            dialect=dialect,
            scopes=[node.type for node in stack if node.type is not None] if stack else None,
            resolver_factory=resolver_factory,
        )

    # Project constant-key JSONExtractString on argMax lazy tables (groups/persons) into the
    # aggregate, so it does not materialize the whole JSON blob per row. Rewrites the call to a
    # property access and re-resolves, so the resolver assigns types rather than us building them.
    # Must run after type resolution and before lazy-table resolution.
    if dialect == "clickhouse" and has_rewritable_json_extract(node, context):
        with context.timings.measure("rewrite_json_extract_to_property"):
            node = rewrite_json_extract_to_property(node, context)
        with context.timings.measure("resolve_types_after_json_pushdown"):
            node = resolve_types(
                node,
                context,
                dialect=dialect,
                scopes=[scope.type for scope in stack if scope.type is not None] if stack else None,
                resolver_factory=resolver_factory,
            )

    if context.enable_type_aware_cast_simplification:
        with context.timings.measure("type_aware_cast_simplification"):
            node = simplify_redundant_type_operations(node, context, dialect)

    # Detect workload from resolved table types and store on context
    with context.timings.measure("workload_detection"):
        collector = WorkloadCollector(default_workload=Workload.DEFAULT)
        collector.visit(node)
        context.workload = collector.get_workload()

    # LOGS-cluster tables (logs, spans, metrics) split attributes across typed `*_map_str/_float/_datetime` Map columns.
    # A type-suffixed attribute key (e.g. `host__str`) only resolves to its physical column via property groups, which
    # are active under OPTIMIZED. Without OPTIMIZED the read falls back to a subscript on the un-suffixed `attributes`
    # alias, where the suffixed key never matches — so `is not` filters match every row and `equals` filters match none
    # (silently wrong, not an error). OPTIMIZED is therefore required for correctness here, not merely a perf mode, so
    # force it for every logs query regardless of any non-OPTIMIZED value a caller may have set — after workload
    # detection, before property resolution reads the modifier.
    if context.workload == Workload.LOGS and context.modifiers.propertyGroupsMode != PropertyGroupsMode.OPTIMIZED:
        context.modifiers.propertyGroupsMode = PropertyGroupsMode.OPTIMIZED

    if context.modifiers.optimizeProjections:
        with context.timings.measure("projection_pushdown"):
            node = pushdown_projections(node, context)
        # Pushdown mutates SelectQueryType.columns, staling cached CTE tables. Drop them so a
        # wrongly pruned column fails loudly at compile time instead of emitting broken SQL.
        context.cte_database_table_cache.clear()

    if dialect in SQL_TARGET_DIALECTS:
        with context.timings.measure("resolve_lazy_tables"):
            resolve_lazy_tables(node, dialect, stack, context, resolver_factory=resolver_factory)

        # Lower JSON-blob property reads to dialect-neutral PropertyAccess nodes. The warehouse dialects have no
        # materialized columns, so logical lowering is the whole story for them (no ClickHouse property resolution).
        with context.timings.measure("lower_property_access"):
            node = lower_property_access(node, context)

    if dialect == "clickhouse":
        with context.timings.measure("resolve_property_types"):
            build_property_swapper(node, context)
            if context.property_swapper is None:
                return None

            # It would be nice to be able to run property swapping after we resolve lazy tables, so that logic added onto the lazy tables
            # could pass through the swapper. However, in the PropertySwapper, the group_properties and the S3 Table join
            # rely on the existence of lazy tables in the AST. They must be run before we resolve lazy tables. Because groups are
            # not currently used in any sort of where clause optimization (WhereClauseExtractor or PersonsTable), this is okay.
            # We also have to call the group property swapper manually in `lazy_tables.py` after we do a join
            node = PropertySwapper(
                timezone=context.property_swapper.timezone,
                group_properties=context.property_swapper.group_properties,
                event_properties={},
                person_properties={},
                context=context,
                setTimeZones=False,
            ).visit(node)

        with context.timings.measure("resolve_lazy_tables"):
            resolve_lazy_tables(node, dialect, stack, context, resolver_factory=resolver_factory)

        with context.timings.measure("swap_properties"):
            node = PropertySwapper(
                timezone=context.property_swapper.timezone,
                group_properties={},
                person_properties=context.property_swapper.person_properties,
                event_properties=context.property_swapper.event_properties,
                context=context,
                setTimeZones=context.modifiers.convertToProjectTimezone is not False,
            ).visit(node)

        # The two passes that replaced the printer's old property handling, in order. Both run AFTER the PropertySwapper
        # passes, so any scalar cast already wraps the property. (1) Lowering replaces every blob `PropertyType` Field with
        # a `PropertyAccess` — a plain "read these keys from this blob", no decision about how. (2) Property resolution
        # then picks the source: each `PropertyAccess` backed by a materialized / skip-index / property-group column is
        # rewritten to read that column; the rest survive and print as the raw JSON extract. The within_non_hogql_query
        # (lightweight-DELETE) path runs through here too; the printer renders every column bare there (the single-table
        # mutation analyzer rejects table prefixes), so no extra marking is needed.
        with context.timings.measure("lower_property_access"):
            node = lower_property_access(node, context)

        # Temporary (June 2026 MaxMind incident: https://posthog.slack.com/archives/C0B9DDSCTF1): recover blanked geoip city/postal reads from the IP via a ClickHouse
        # dictionary. Runs on the lowered AST so the reads it adds are plain PropertyAccess nodes, which the resolution
        # pass below routes to materialized columns. Operator-controlled via env only, per team. Decided exactly once
        # per query, on the context, so the printer's `_lookupGeoip*` gate can never disagree with the transform.
        # Never applies within_non_hogql_query: those fragments splice into DELETE mutations (data deletion requests)
        # and legacy filters, where the matched row set must not depend on env/probe state and a missing dictionary
        # would wedge the sticky mutation queue. Remove with the transform.
        context.geoip_dict_fallback_enabled = (
            not context.within_non_hogql_query and geoip_dict_fallback_enabled_for_team(context.team_id)
        )
        if context.geoip_dict_fallback_enabled:
            with context.timings.measure("geoip_dict_fallback"):
                node = (
                    apply_geoip_dict_fallback_delete_this_function_when_inc_2026_06_11_maxmind_missing_data_is_resolved(
                        node, context
                    )
                )

        # Cohort-gated events data retention: floor every events scan to now() - retention. Computed once here
        # (the per-scan printer hook can't afford the team lookup + flag eval); the printer reads it off the context.
        # Gated on the backend-only apply_events_retention_floor flag so server-side paths that must bypass the floor
        # — e.g. the GDPR data-deletion mutation path — can opt out; the flag can't be set from a query, so the
        # enforcement floor still can't be circumvented by a query-supplied modifier.
        with context.timings.measure("events_retention_floor"):
            if context.apply_events_retention_floor:
                context.events_retention_months = events_retention_months_for_team(context.team, context.team_id)

        # Events predicate pushdown runs on the lowered AST (between lowering and property resolution), so it matches the
        # dialect-neutral PropertyAccess form. Its pre-filtering subquery projects only source columns (raw blobs and
        # bare events columns); outer blob references are re-typed onto the subquery, so the resolution pass substitutes
        # physical columns only inside the subquery body — where the real events table is in scope — and outer
        # references print as JSON extracts over the projected blob.
        if events_pushdown_enabled(context.modifiers):
            with context.timings.measure("events_predicate_pushdown"):
                node = apply_events_predicate_pushdown(node, context)

        with context.timings.measure("clickhouse_property_resolution"):
            node = clickhouse_property_resolution(node, context)

        # We support global query settings, and local subquery settings.
        # If the global query is a select query with settings, merge the two.
        if isinstance(node, ast.SelectQuery) and node.settings is not None and settings is not None:
            for key, value in node.settings.model_dump().items():
                if value is not None:
                    settings.__setattr__(key, value)
            node.settings = None

    if context.modifiers.inCohortVia == InCohortVia.LEFTJOIN:
        with context.timings.measure("resolve_in_cohorts"):
            resolve_in_cohorts(node, dialect, stack, context, resolver_factory=resolver_factory)

    # Drop argmax_select's tuple()/tupleElement() wrap for non-nullable columns; runs last so resolved nullability is final. ClickHouse-only.
    if dialect == "clickhouse":
        with context.timings.measure("simplify_argmax_over_non_nullable"):
            node = simplify_argmax_over_non_nullable(node, context)

    # We add a team_id guard right before printing. It's not a separate step here.
    return node


def print_prepared_ast(
    node: _T_AST,
    context: HogQLContext,
    dialect: HogQLDialect,
    stack: list[ast.SelectQuery] | None = None,
    settings: HogQLGlobalSettings | None = None,
    pretty: bool = False,
) -> str:
    with context.timings.measure("printer"):
        printer_stack = cast(list[ast.AST], stack or [])

        printer_class = PRINTER_CLASSES.get(dialect)
        if printer_class is None:
            raise InternalHogQLError(f"Invalid SQL dialect: {dialect}")

        printer = printer_class(
            context=context,
            stack=printer_stack,
            settings=settings,
            pretty=pretty,
        )

        return printer.visit(node)
