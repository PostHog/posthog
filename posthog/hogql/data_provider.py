from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, NotRequired, Optional, Protocol, TypedDict

from posthog.hogql.team_context import HogQLTeamContext

if TYPE_CHECKING:
    # Type-only: ast.py transitively imports this module (via resolver_utils),
    # so a runtime import would be circular.
    from posthog.hogql import ast

PropertyKind = Literal["event", "person", "group"]
ActionScope = Literal["team", "project"]
CohortRefKind = Literal["id", "name"]

# Composite lookup keys for StaticDataProvider's in-memory tables. Frozen dataclasses (not tuples)
# so a key can only be built explicitly and read by name — a raw tuple can't silently stand in.


@dataclass(frozen=True)
class PersonWarehousePropertyKey:
    field_name: str | int  # the field the warehouse table is joined to persons as
    property_key: str


@dataclass(frozen=True)
class MaterializedColumnKey:
    table: str  # ClickHouse table name, e.g. "events"
    column: str  # ClickHouse column holding the JSON, e.g. "properties"
    property_name: str


@dataclass(frozen=True)
class ActionRefKey:
    scope: ActionScope
    ref: int | str  # action id, or name when scope is "project"


@dataclass(frozen=True)
class CohortRefKey:
    kind: CohortRefKind  # "id" or "name"
    ref: int | str


@dataclass(frozen=True)
class TextEmbeddingKey:
    text: str
    model: Optional[str]


# A property the requesting user may not read: ``(property name, PropertyDefinition.Type value)``.
# A bare tuple (not a NamedTuple): it's built in many call sites as plain pairs and consumed by
# unpacking (``for name, property_type in ...``), so an alias documents the shape without forcing
# every construction site to switch to a constructor.
RestrictedProperty = tuple[str, int]


@dataclass(frozen=True)
class QueryExpansion:
    """A canned ``expand_query`` result for StaticDataProvider: a query node and what it expands to."""

    node: Any  # a posthog.schema query node (e.g. a HogQLX tag); matched by value equality
    query: "ast.SelectQuery | ast.SelectSetQuery"


@dataclass(frozen=True)
class CohortRef:
    """The cohort columns the engine reads when rewriting IN COHORT comparisons."""

    id: int
    is_static: bool
    version: Optional[int]
    name: Optional[str] = None


@dataclass(frozen=True)
class ActionRef:
    """Plain identity of an action, for engine-side notices and error messages."""

    id: int
    name: Optional[str]


@dataclass(frozen=True)
class InsightVariableInfo:
    """The insight-variable fields the engine reads when substituting placeholders."""

    code_name: Optional[str]
    default_value: Any


@dataclass(frozen=True)
class MaterializedColumnInfo:
    """A physical ClickHouse column backing a property read, as the engine consumes it.

    ``type`` is the ClickHouse type string (e.g. ``"Nullable(Float64)"``); the ``has_*``
    flags say which skip indexes exist on the column, which gates the engine's
    bare-column comparison rewrites.
    """

    name: str
    type: str
    is_nullable: bool
    has_minmax_index: bool = False
    has_bloom_filter_index: bool = False
    has_ngram_lower_index: bool = False
    has_bloom_filter_lower_index: bool = False


class PropertyTypeInfo(TypedDict):
    """The type facts the engine needs about one property.

    ``type`` is the property's inferred type — one of the PropertyDefinition property types
    (``"DateTime"``, ``"String"``, ``"Numeric"``, ``"Boolean"``, ``"Duration"``) — used to
    read and cast the otherwise-untyped raw value. ``dmat`` names a materialized column that
    backs the property; it is present only for event properties that have one, and its
    absence means the value is read from JSON.
    """

    type: str
    dmat: NotRequired[str]


@dataclass(frozen=True)
class PropertyTypes:
    """The types of the properties a query references, grouped by where the property lives.

    Each map is keyed by property: the bare name for ``event`` and ``person``, and
    ``"{group_type_index}_{name}"`` for ``group`` (e.g. ``"0_industry"``), since the same name
    can exist under different group types. A property missing from its map has no known type.
    """

    event: dict[str, PropertyTypeInfo] = field(default_factory=dict)
    person: dict[str, PropertyTypeInfo] = field(default_factory=dict)
    group: dict[str, PropertyTypeInfo] = field(default_factory=dict)


class DataProvider(Protocol):
    """The HogQL engine's port for everything it needs from the outside world mid-compile.

    The engine asks for data while compiling — property types, cohort definitions,
    warehouse catalog entries — and a provider answers. Engine code depends only on
    this protocol; the Django-backed implementation (``posthog.hogql_django_provider``)
    answers from the ORM, while tests and future out-of-process callers inject
    ``StaticDataProvider`` (or any other implementation) instead.

    Design contract for methods on this protocol:
    - take explicit references (names, ids), never AST-wide context
    - return plain values or HogQL AST nodes, never Django models or querysets
    - batched signatures (lists in, maps out) where the call site naturally has a batch
    """

    @property
    def team_context(self) -> HogQLTeamContext:
        """Plain-data snapshot of the requesting team's configuration."""
        ...

    def person_warehouse_property_type(self, field_name: str | int, property_key: str) -> Optional[str]:
        """HogQL type name of ``property_key`` on the warehouse table joined to persons as ``field_name``.

        Returns e.g. ``"BooleanDatabaseField"``, or ``None`` when the column carries no
        type. Raises if no join or no table exists for ``field_name``.
        """
        ...

    def persons_join_uses_inner_join(self) -> bool:
        """Whether joins to the persons table should be INNER instead of LEFT.

        On the Django side this is a per-organization feature flag (personless events
        not supported); the engine just applies the verdict.
        """
        ...

    def property_type(self, kind: PropertyKind, name: str, group_type_index: Optional[int] = None) -> Optional[str]:
        """Defined property type (e.g. ``"Boolean"``) of a single property, or ``None``."""
        ...

    def property_types(
        self,
        event_properties: list[str],
        person_properties: list[str],
        group_properties: dict[int, list[str]],
    ) -> PropertyTypes:
        """Batched property-type lookup for everything a query references."""
        ...

    def materialized_column(self, table: str, column: str, property_name: str) -> Optional[MaterializedColumnInfo]:
        """The enabled materialized column backing ``<table>.<column>.<property_name>``, or ``None``.

        ``table`` and ``column`` are ClickHouse names (``"events"``, ``"properties"``).
        ``None`` means the property stays a JSON read — whether because nothing is
        materialized or because the deployment has materialization disabled is the
        provider's concern (on the Django side, the ``MATERIALIZED_COLUMNS_ENABLED``
        instance setting).
        """
        ...

    def actions(self, ref: int | str, scope: ActionScope) -> list[ActionRef]:
        """Actions matching ``ref`` — an id, or a name when ``scope`` is ``"project"``.

        ``"team"`` scope matches the requesting team only (retention entities);
        ``"project"`` scope matches any team in the project (the ``action()`` function).
        The list lets the engine keep its existing not-found and ambiguity errors.
        """
        ...

    def action_expr(self, action_id: int, events_alias: Optional[str] = None) -> Optional["ast.Expr"]:
        """The action's step filters converted to an expression, or ``None`` if it doesn't exist.

        The action may belong to a sibling team in the project; its steps compile with the
        owning team's settings (timezone, path cleaning, warehouse joins).
        """
        ...

    def insight_variables(self, variable_ids: list[str]) -> list[InsightVariableInfo]:
        """The requesting team's insight variables among ``variable_ids``."""
        ...

    def expand_query(self, query_node: Any) -> "ast.SelectQuery | ast.SelectSetQuery":
        """Expand a query-schema node (from a HogQLX tag like ``<RetentionQuery/>``) to a select query.

        ``query_node`` is a pydantic node from ``posthog.schema``; the Django
        implementation instantiates the matching query runner and returns its query.
        """
        ...

    def cohort_id(self, ref: int | str) -> int:
        """Resolve a cohort property reference to the cohort's id; raises if it doesn't exist.

        Unlike ``cohorts``, deleted cohorts still resolve — matching how cohort
        property filters have always behaved.
        """
        ...

    def cohorts(self, ref: int | str, by: CohortRefKind) -> list[CohortRef]:
        """Non-deleted cohorts in the project matching an id or a name.

        The list lets the engine keep its existing not-found and ambiguity errors.
        """
        ...

    def inline_cohort(self, cohort_id: int, auto_gated: bool) -> Optional["ast.SelectQuery | ast.SelectSetQuery"]:
        """The cohort's definition compiled to a select query, for inline evaluation.

        Returns ``None`` when inlining shouldn't happen. With ``auto_gated`` the
        decision belongs to the provider (on the Django side: a feature flag plus the
        cohort's recent calculation history); without it the caller already decided.
        """
        ...

    def embed_text(self, text: str, model: Optional[str] = None) -> list[float]:
        """Embedding vector for ``text`` — the ``embedText()`` HogQL function."""
        ...

    def restricted_properties(self) -> set[RestrictedProperty]:
        """The properties the requesting user is not allowed to read."""
        ...


@dataclass
class StaticDataProvider:
    """A ``DataProvider`` answering from in-memory data — no database, no Django.

    Used by engine tests to compile queries with zero I/O. Lookups are strict: asking
    for data that wasn't provided raises ``KeyError``, surfacing exactly which inputs a
    query needs.
    """

    team_context: HogQLTeamContext
    person_warehouse_property_types: dict[PersonWarehousePropertyKey, Optional[str]] = field(default_factory=dict)
    persons_inner_join: bool = False
    # Full property-type catalog; lookups return the subset a query asks for. A property
    # absent from the catalog is simply untyped — a legitimate state, not an error.
    property_type_catalog: PropertyTypes = field(default_factory=PropertyTypes)
    # A property absent here is simply not materialized — also a legitimate state.
    materialized_columns: dict[MaterializedColumnKey, MaterializedColumnInfo] = field(default_factory=dict)
    action_refs: dict[ActionRefKey, list[ActionRef]] = field(default_factory=dict)
    action_exprs: dict[int, "ast.Expr"] = field(default_factory=dict)
    insight_variables_by_id: dict[str, InsightVariableInfo] = field(default_factory=dict)
    query_expansions: list[QueryExpansion] = field(default_factory=list)
    cohort_ids: dict[int | str, int] = field(default_factory=dict)
    cohort_refs: dict[CohortRefKey, list[CohortRef]] = field(default_factory=dict)
    inline_cohort_queries: dict[int, "ast.SelectQuery | ast.SelectSetQuery"] = field(default_factory=dict)
    text_embeddings: dict[TextEmbeddingKey, list[float]] = field(default_factory=dict)
    restricted_properties_set: set[RestrictedProperty] = field(default_factory=set)

    def person_warehouse_property_type(self, field_name: str | int, property_key: str) -> Optional[str]:
        return self.person_warehouse_property_types[PersonWarehousePropertyKey(field_name, property_key)]

    def persons_join_uses_inner_join(self) -> bool:
        return self.persons_inner_join

    def property_type(self, kind: PropertyKind, name: str, group_type_index: Optional[int] = None) -> Optional[str]:
        if kind == "event":
            info = self.property_type_catalog.event.get(name)
        elif kind == "person":
            info = self.property_type_catalog.person.get(name)
        else:
            info = self.property_type_catalog.group.get(f"{group_type_index}_{name}")
        return info.get("type") if info else None

    def property_types(
        self,
        event_properties: list[str],
        person_properties: list[str],
        group_properties: dict[int, list[str]],
    ) -> PropertyTypes:
        group_keys = {f"{index}_{name}" for index, names in group_properties.items() for name in names}
        requested_events = set(event_properties)
        requested_persons = set(person_properties)
        return PropertyTypes(
            event={k: v for k, v in self.property_type_catalog.event.items() if k in requested_events},
            person={k: v for k, v in self.property_type_catalog.person.items() if k in requested_persons},
            group={k: v for k, v in self.property_type_catalog.group.items() if k in group_keys},
        )

    def materialized_column(self, table: str, column: str, property_name: str) -> Optional[MaterializedColumnInfo]:
        return self.materialized_columns.get(MaterializedColumnKey(table, column, property_name))

    def actions(self, ref: int | str, scope: ActionScope) -> list[ActionRef]:
        return self.action_refs.get(ActionRefKey(scope, ref), [])

    def action_expr(self, action_id: int, events_alias: Optional[str] = None) -> Optional["ast.Expr"]:
        return self.action_exprs.get(action_id)

    def insight_variables(self, variable_ids: list[str]) -> list[InsightVariableInfo]:
        return [
            self.insight_variables_by_id[variable_id]
            for variable_id in variable_ids
            if variable_id in self.insight_variables_by_id
        ]

    def expand_query(self, query_node: Any) -> "ast.SelectQuery | ast.SelectSetQuery":
        for entry in self.query_expansions:
            if entry.node == query_node:
                return entry.query
        raise KeyError(f"No expansion provided for query node {type(query_node).__name__}")

    def cohort_id(self, ref: int | str) -> int:
        return self.cohort_ids[ref]

    def cohorts(self, ref: int | str, by: CohortRefKind) -> list[CohortRef]:
        return self.cohort_refs.get(CohortRefKey(by, ref), [])

    def inline_cohort(self, cohort_id: int, auto_gated: bool) -> Optional["ast.SelectQuery | ast.SelectSetQuery"]:
        return self.inline_cohort_queries.get(cohort_id)

    def embed_text(self, text: str, model: Optional[str] = None) -> list[float]:
        return self.text_embeddings[TextEmbeddingKey(text, model)]

    def restricted_properties(self) -> set[RestrictedProperty]:
        return self.restricted_properties_set
