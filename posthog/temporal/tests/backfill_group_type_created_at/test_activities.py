from datetime import UTC, datetime

import pytest

from posthog.temporal.backfill_group_type_created_at.activities import _build_backfill_plan

CREATED_AT = datetime(2026, 5, 31, 22, 33, tzinfo=UTC)
EARLIER = datetime(2026, 5, 12, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 6, 6, 0, 0, tzinfo=UTC)


def _mapping(index: int, created_at: datetime | None) -> dict:
    return {"group_type": f"g{index}", "group_type_index": index, "created_at": created_at}


def test_build_plan_lowers_created_at_to_earliest_event():
    updates, skipped = _build_backfill_plan([_mapping(0, CREATED_AT)], {0: EARLIER})

    assert skipped == []
    assert updates == [
        {
            "group_type": "g0",
            "group_type_index": 0,
            "current_created_at": CREATED_AT.isoformat(),
            "new_created_at": EARLIER.isoformat(),
        }
    ]


@pytest.mark.parametrize(
    "created_at,earliest,expected_reason",
    [
        (None, {0: EARLIER}, "created_at already null"),
        (CREATED_AT, {}, "no events carry this group"),
        (CREATED_AT, {0: LATER}, "created_at already at or before earliest event"),
        (CREATED_AT, {0: CREATED_AT}, "created_at already at or before earliest event"),
    ],
)
def test_build_plan_skips_when_no_correction_needed(created_at, earliest, expected_reason):
    updates, skipped = _build_backfill_plan([_mapping(0, created_at)], earliest)

    assert updates == []
    assert len(skipped) == 1
    assert skipped[0]["reason"] == expected_reason


def test_build_plan_handles_mixed_mappings():
    mappings = [_mapping(0, CREATED_AT), _mapping(1, None), _mapping(2, CREATED_AT)]
    earliest = {0: EARLIER, 2: LATER}

    updates, skipped = _build_backfill_plan(mappings, earliest)

    assert [u["group_type_index"] for u in updates] == [0]
    assert {s["group_type_index"] for s in skipped} == {1, 2}
