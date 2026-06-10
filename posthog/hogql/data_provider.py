from dataclasses import dataclass, field
from typing import Any, Literal, Optional, Protocol

from posthog.hogql import ast
from posthog.hogql.team_context import HogQLTeamContext

PropertyKind = Literal["event", "person", "group"]
ActionScope = Literal["team", "project"]


@dataclass(frozen=True)
class ActionRef:
    """Plain identity of an action, for engine-side notices and error messages."""

    id: int
    name: Optional[str]


@dataclass(frozen=True)
class InsightVariableInfo:
    """The two fields of an insight variable the engine reads when substituting placeholders."""

    code_name: Optional[str]
    default_value: Any


@dataclass(frozen=True)
class PropertyTypes:
    """Property-type maps for the properties a query references.

    Shapes match what ``PropertySwapper`` consumes: values are ``{"type": ...}`` dicts,
    event entries may carry a ``"dmat"`` materialized-slot column, and group keys are
    ``"{group_type_index}_{name}"``. Properties without a known type are absent.
    """

    event: dict[str, dict[str, str | None]] = field(default_factory=dict)
    person: dict[str, dict[str, str | None]] = field(default_factory=dict)
    group: dict[str, dict[str, str | None]] = field(default_factory=dict)


class DataProvider(Protocol):
    """The HogQL engine's port for everything it needs from the outside world mid-compile.

    The engine asks for data while compiling — property types, cohort definitions,
    warehouse catalog entries — and a provider answers. Engine code depends only on
    this protocol; the Django-backed implementation (``posthog.hogql.django_provider``)
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

    def actions(self, ref: int | str, scope: ActionScope) -> list[ActionRef]:
        """Actions matching ``ref`` — an id, or a name when ``scope`` is ``"project"``.

        ``"team"`` scope matches the requesting team only (retention entities);
        ``"project"`` scope matches any team in the project (the ``action()`` function).
        The list lets the engine keep its existing not-found and ambiguity errors.
        """
        ...

    def action_expr(self, action_id: int, events_alias: Optional[str] = None) -> Optional[ast.Expr]:
        """The action's step filters converted to an expression, or ``None`` if it doesn't exist."""
        ...

    def insight_variables(self, variable_ids: list[str]) -> list[InsightVariableInfo]:
        """The requesting team's insight variables among ``variable_ids``."""
        ...


@dataclass
class StaticDataProvider:
    """A ``DataProvider`` answering from in-memory data — no database, no Django.

    Used by engine tests to compile queries with zero I/O. Lookups are strict: asking
    for data that wasn't provided raises ``KeyError``, surfacing exactly which inputs a
    query needs.
    """

    team_context: HogQLTeamContext
    person_warehouse_property_types: dict[tuple[str | int, str], Optional[str]] = field(default_factory=dict)
    persons_inner_join: bool = False
    # Full property-type catalog; lookups return the subset a query asks for. A property
    # absent from the catalog is simply untyped — a legitimate state, not an error.
    property_type_catalog: PropertyTypes = field(default_factory=PropertyTypes)
    action_refs: dict[tuple[ActionScope, int | str], list[ActionRef]] = field(default_factory=dict)
    action_exprs: dict[int, ast.Expr] = field(default_factory=dict)
    insight_variables_by_id: dict[str, InsightVariableInfo] = field(default_factory=dict)

    def person_warehouse_property_type(self, field_name: str | int, property_key: str) -> Optional[str]:
        return self.person_warehouse_property_types[(field_name, property_key)]

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

    def actions(self, ref: int | str, scope: ActionScope) -> list[ActionRef]:
        return self.action_refs.get((scope, ref), [])

    def action_expr(self, action_id: int, events_alias: Optional[str] = None) -> Optional[ast.Expr]:
        return self.action_exprs.get(action_id)

    def insight_variables(self, variable_ids: list[str]) -> list[InsightVariableInfo]:
        return [
            self.insight_variables_by_id[variable_id]
            for variable_id in variable_ids
            if variable_id in self.insight_variables_by_id
        ]
