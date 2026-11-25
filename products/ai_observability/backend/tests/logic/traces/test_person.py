from parameterized import parameterized

from products.ai_observability.backend.logic.traces.person import person_label
from products.ai_observability.backend.logic.traces.trace_queries import PersonRow


@parameterized.expand(
    [
        ("the display name", "Ada", "Ada"),
        ("the distinct id without one", None, "user-1"),
    ]
)
def test_person_label(_name: str, display_name: str | None, expected: str) -> None:
    assert person_label(PersonRow(distinct_id="user-1", display_name=display_name)) == expected
