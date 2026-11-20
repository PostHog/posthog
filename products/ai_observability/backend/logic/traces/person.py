from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .trace_queries import PersonRow


class IdentifiedEvent(Protocol):
    @property
    def event(self) -> str: ...

    @property
    def timestamp(self) -> datetime: ...

    @property
    def distinct_id(self) -> str: ...


def trace_distinct_id(rows: Sequence[IdentifiedEvent]) -> str | None:
    identified = sorted(
        (row for row in rows if row.distinct_id),
        key=lambda row: (row.event != "$ai_trace", row.timestamp),
    )
    return identified[0].distinct_id if identified else None


def person_label(person: "PersonRow") -> str:
    return person.display_name or person.distinct_id
