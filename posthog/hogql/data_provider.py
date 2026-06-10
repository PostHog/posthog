from dataclasses import dataclass, field
from typing import Optional, Protocol

from posthog.hogql.team_context import HogQLTeamContext


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


@dataclass
class StaticDataProvider:
    """A ``DataProvider`` answering from in-memory data — no database, no Django.

    Used by engine tests to compile queries with zero I/O. Lookups are strict: asking
    for data that wasn't provided raises ``KeyError``, surfacing exactly which inputs a
    query needs.
    """

    team_context: HogQLTeamContext
    person_warehouse_property_types: dict[tuple[str | int, str], Optional[str]] = field(default_factory=dict)

    def person_warehouse_property_type(self, field_name: str | int, property_key: str) -> Optional[str]:
        return self.person_warehouse_property_types[(field_name, property_key)]
