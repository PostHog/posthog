from dataclasses import dataclass, field
from functools import cached_property
from typing import TYPE_CHECKING, Any, Literal, Optional

from posthog.hogql.constants import LimitContext
from posthog.hogql.timings import HogQLTimings

from posthog.clickhouse.workload import Workload

if TYPE_CHECKING:
    from posthog.schema import DataWarehouseSyncWarning, HogQLNotice, HogQLQueryModifiers

    from posthog.hogql.database.database import Database
    from posthog.hogql.database.models import Table
    from posthog.hogql.observability import HogQLTypeObservability
    from posthog.hogql.transforms.property_types import PropertySwapper

    from posthog.clickhouse.client.execute import ClickHouseExternalTable
    from posthog.models import Team, User
    from posthog.rbac.user_access_control import UserAccessControl


def _default_modifiers() -> "HogQLQueryModifiers":
    # Deferred: posthog.schema (the pydantic models) stays off django.setup(); this module
    # loads there via the legacy filter classes and the warehouse models.
    from posthog.schema import HogQLQueryModifiers  # noqa: PLC0415

    return HogQLQueryModifiers()


@dataclass
class HogQLFieldAccess:
    input: list[str]
    type: Optional[Literal["event", "event.properties", "person", "person.properties"]]
    field: Optional[str]
    sql: str


@dataclass
class HogQLContext:
    """Context given to a HogQL expression printer"""

    # Team making the queries
    team_id: Optional[int] = None
    # Team making the queries - if team is passed in, then the team isn't queried when creating the database
    team: Optional["Team"] = None

    # User making the queries - used for access control on system tables
    user: Optional["User"] = None
    # Preloaded access-control snapshot for `user`, shared so schema filtering and the query
    # cache fingerprint resolve access from the same rows (one bulk preload per run).
    user_access_control: Optional["UserAccessControl"] = None

    # SECURITY-SENSITIVE: bypass for HogQL access control on warehouse tables.
    # Set ONLY when running in a context without a user (e.g., internal data imports, schema introspection).
    # Every call site that sets this MUST include an inline comment explaining why.
    bypass_warehouse_access_control: bool = False

    # Virtual database we're querying, will be populated from team_id if not present
    database: Optional["Database"] = None
    # Metadata discovered for a direct Postgres connection, if one is selected
    direct_postgres_connection_metadata: dict[str, Any] | None = None
    # If set, will save string constants to this dict. Inlines strings into the query if None.
    values: dict = field(default_factory=dict)
    # Query-scoped ClickHouse external data tables accumulated during printing (keyed by table name).
    # Lets `system.information_schema` ship its rows out-of-band instead of inlining them; read by the
    # executor and passed to `sync_execute`.
    external_tables: dict[str, "ClickHouseExternalTable"] = field(default_factory=dict, compare=False, repr=False)
    # Are we small part of a non-HogQL query? If so, use custom syntax for accessed person properties.
    within_non_hogql_query: bool = False
    # Enable full SELECT queries and subqueries in ClickHouse
    enable_select_queries: bool = False
    # Do we apply a limit of MAX_SELECT_RETURNED_ROWS=10000 to the topmost select query?
    limit_top_select: bool = True
    # Context for determining the appropriate limit to apply
    limit_context: Optional[LimitContext] = None
    # Apply a FORMAT clause to output data in given format.
    output_format: str | None = None
    # Globals that will be resolved in the context of the query
    globals: Optional[dict] = None
    # Per-query data that query runners want to ingest into the HogQL resolution (e.g. pending updates
    # merged into a table via UNION ALL in error tracking).
    data_to_ingest: dict[str, Any] = field(default_factory=dict)

    # Warnings returned with the metadata query
    warnings: list["HogQLNotice"] = field(default_factory=list)
    # Notices returned with the metadata query
    notices: list["HogQLNotice"] = field(default_factory=list)
    # Errors returned with the metadata query
    errors: list["HogQLNotice"] = field(default_factory=list)

    # Data warehouse sync warnings collected while resolving warehouse tables referenced by the query.
    # Keyed by (table_id, schema_name) to dedupe when a table is referenced multiple times.
    data_warehouse_sync_warnings: dict[tuple[str, str], "DataWarehouseSyncWarning"] = field(default_factory=dict)

    # Resources with object-level access restrictions referenced by the query, collected while printing
    # system tables. A set dedupes when several system tables share an access scope (e.g. system.dashboards
    # and system.dashboard_tiles both scope "dashboard"). Turned into a single AccessControlFilterWarning
    # on the response by build_access_control_warning.
    access_control_restricted_resources: set[str] = field(default_factory=set)

    # Timings in seconds for different parts of the HogQL query
    timings: HogQLTimings = field(default_factory=HogQLTimings)
    # Modifications requested by the HogQL client
    modifiers: "HogQLQueryModifiers" = field(default_factory=_default_modifiers)
    # Enables more verbose output for debugging
    debug: bool = False
    # Internal optimizer flag. Keep disabled until typed rewrites have broader compatibility coverage.
    enable_type_aware_cast_simplification: bool = False

    # Optional per-query HogQL type-system observability accumulator.
    type_observability: Optional["HogQLTypeObservability"] = None
    # Bounded source/surface label for type-system observability metrics.
    observability_source: str = "unknown"

    property_swapper: Optional["PropertySwapper"] = None
    # Workload detected during AST resolution (set by prepare_ast_for_printing)
    workload: Optional[Workload] = None
    # Per-query cache of the `system.information_schema` introspection result (populated lazily in
    # posthog/hogql/database/schema/information_schema.py). A dict keyed by the pushed-down table
    # filter, so information_schema tables resolving to the same bound within one query walk the
    # database (and fire the warehouse metadata ORM queries) only once.
    information_schema_introspection: Optional[Any] = field(default=None, compare=False, repr=False)
    # Property-level access control: set of (property_name, PropertyDefinition.Type) tuples
    # that the current user is denied access to. Populated before type resolution so that
    # FieldType.get_child() can raise QueryError for restricted properties.
    restricted_properties: Optional[set[tuple[str, int]]] = None

    # Per-query cache of CTE synthetic tables, keyed by id() of the CTE's SelectQueryType. Value pins a
    # strong ref to the keyed type so its id can't be reused while cached; lookups verify identity.
    cte_database_table_cache: dict[int, tuple[Any, "Table"]] = field(default_factory=dict, compare=False, repr=False)

    # Cohort-gated events data retention: when set, the ClickHouse printer floors every events-table scan to
    # now() - toIntervalMonth(this). Computed once per query in prepare_ast_for_printing; None means not enforced.
    events_retention_months: Optional[int] = None
    # Backend-only switch for the events-retention floor. Defaults on; server-side paths that must act on all rows
    # regardless of retention — notably the GDPR data-deletion mutation path — set this False. Deliberately NOT a
    # HogQLQueryModifier, so a query can't disable enforcement.
    apply_events_retention_floor: bool = True

    def __post_init__(self):
        if self.team:
            self.team_id = self.team.id

    def add_value(self, value: Any) -> str:
        key = f"hogql_val_{len(self.values)}"
        self.values[key] = value
        return f"%({key})s"

    def add_sensitive_value(self, value: Any) -> str:
        key = f"hogql_val_{len(self.values)}_sensitive"
        self.values[key] = value
        return f"%({key})s"

    def add_notice(
        self,
        message: str,
        start: Optional[int] = None,
        end: Optional[int] = None,
        fix: Optional[str] = None,
    ):
        if not any(n.start == start and n.end == end and n.message == message and n.fix == fix for n in self.notices):
            from posthog.schema import HogQLNotice  # noqa: PLC0415

            self.notices.append(HogQLNotice(start=start, end=end, message=message, fix=fix))

    def add_warning(
        self,
        message: str,
        start: Optional[int] = None,
        end: Optional[int] = None,
        fix: Optional[str] = None,
    ):
        if not any(n.start == start and n.end == end and n.message == message and n.fix == fix for n in self.warnings):
            from posthog.schema import HogQLNotice  # noqa: PLC0415

            self.warnings.append(HogQLNotice(start=start, end=end, message=message, fix=fix))

    def add_error(
        self,
        message: str,
        start: Optional[int] = None,
        end: Optional[int] = None,
        fix: Optional[str] = None,
    ):
        if not any(n.start == start and n.end == end and n.message == message and n.fix == fix for n in self.errors):
            from posthog.schema import HogQLNotice  # noqa: PLC0415

            self.errors.append(HogQLNotice(start=start, end=end, message=message, fix=fix))

    def add_data_warehouse_sync_warning(self, table_id: str, warning: "DataWarehouseSyncWarning") -> None:
        self.data_warehouse_sync_warnings[(table_id, warning.schema_name)] = warning

    @cached_property
    def project_id(self) -> int:
        from posthog.models import Team

        if not self.team and not self.team_id:
            raise ValueError("Either team or team_id must be set to determine project_id")
        team = self.team or Team.objects.only("project_id").get(id=self.team_id)
        return team.project_id
