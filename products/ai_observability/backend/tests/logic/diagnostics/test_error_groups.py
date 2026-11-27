from datetime import UTC, datetime, timedelta

from parameterized import parameterized

from products.ai_observability.backend.logic.diagnostics.error_groups import first_seen_in_range

RANGE_START = datetime(2026, 9, 1, tzinfo=UTC)


@parameterized.expand(
    [
        ("at_the_range_start", RANGE_START, True),
        ("before_the_range_start", RANGE_START - timedelta(microseconds=1), False),
        ("never_seen", None, False),
    ]
)
def test_an_error_is_new_when_first_seen_from_the_range_start(
    _name: str, first_seen: datetime | None, expected: bool
) -> None:
    assert first_seen_in_range(first_seen, RANGE_START) is expected
