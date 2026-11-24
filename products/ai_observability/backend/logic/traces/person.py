from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .trace_queries import PersonRow


def person_label(person: "PersonRow") -> str:
    return person.display_name or person.distinct_id
