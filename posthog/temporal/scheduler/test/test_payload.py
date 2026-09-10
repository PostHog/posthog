from collections.abc import Sequence

import pytest

from temporalio.converter import DataConverter

from posthog.temporal.scheduler.payload import (
    MAX_SCHEDULER_PAYLOAD_BYTES,
    select_items_within_temporal_payload,
    temporal_payload_size_bytes,
)


def _build_payload(items: Sequence[str]) -> dict[str, object]:
    return {"scheduler": "test-scheduler", "items": list(items)}


@pytest.mark.asyncio
async def test_temporal_payload_size_matches_sdk_wire_payload_size() -> None:
    value = _build_payload(["one", "two"])

    encoded = await DataConverter.default.encode([value])
    size = await temporal_payload_size_bytes(value)

    assert size == sum(payload.ByteSize() for payload in encoded)
    assert size > sum(len(payload.data) for payload in encoded)


@pytest.mark.asyncio
async def test_select_items_preserves_order_and_respects_item_limit() -> None:
    result = await select_items_within_temporal_payload(
        ["one", "two", "three"],
        build_payload=_build_payload,
        max_items=2,
    )

    assert result.items == ("one", "two")
    assert result.encoded_size_bytes == await temporal_payload_size_bytes(_build_payload(result.items))
    assert result.limited_by == "item_limit"


@pytest.mark.asyncio
async def test_select_items_accepts_payload_that_exactly_fits_byte_budget() -> None:
    items = ["one", "two"]
    exact_size = await temporal_payload_size_bytes(_build_payload(items))

    result = await select_items_within_temporal_payload(
        items,
        build_payload=_build_payload,
        max_items=2,
        payload_budget_bytes=exact_size,
    )

    assert result.items == ("one", "two")
    assert result.encoded_size_bytes == exact_size
    assert result.limited_by == "none"


@pytest.mark.asyncio
async def test_select_items_uses_safe_prefix_within_byte_budget() -> None:
    items = ["a" * 500, "b" * 500, "c" * 500]
    two_item_size = await temporal_payload_size_bytes(_build_payload(items[:2]))
    assert await temporal_payload_size_bytes(_build_payload(items)) > two_item_size

    result = await select_items_within_temporal_payload(
        items,
        build_payload=_build_payload,
        max_items=3,
        payload_budget_bytes=two_item_size,
    )

    assert result.items == tuple(items[:2])
    assert result.encoded_size_bytes == two_item_size
    assert result.limited_by == "byte_limit"


@pytest.mark.asyncio
async def test_select_items_reports_oversized_first_item_without_exceeding_budget() -> None:
    empty_size = await temporal_payload_size_bytes(_build_payload([]))

    result = await select_items_within_temporal_payload(
        ["x" * 500],
        build_payload=_build_payload,
        max_items=1,
        payload_budget_bytes=empty_size,
    )

    assert result.items == ()
    assert result.encoded_size_bytes == empty_size
    assert result.limited_by == "byte_limit"


@pytest.mark.asyncio
async def test_select_items_rejects_invalid_or_unsafe_limits() -> None:
    for max_items, payload_budget_bytes, error in [
        (0, MAX_SCHEDULER_PAYLOAD_BYTES, "max_items"),
        (1, 0, "payload_budget_bytes"),
        (1, MAX_SCHEDULER_PAYLOAD_BYTES + 1, "hard maximum"),
    ]:
        with pytest.raises(ValueError, match=error):
            await select_items_within_temporal_payload(
                ["one"],
                build_payload=_build_payload,
                max_items=max_items,
                payload_budget_bytes=payload_budget_bytes,
            )


@pytest.mark.asyncio
async def test_select_items_rejects_fixed_envelope_above_budget() -> None:
    def build_oversized_payload(items: Sequence[str]) -> dict[str, object]:
        return {"fixed": "x" * 1_000, "items": list(items)}

    empty_size = await temporal_payload_size_bytes(build_oversized_payload([]))

    with pytest.raises(ValueError, match="fixed payload envelope"):
        await select_items_within_temporal_payload(
            ["one"],
            build_payload=build_oversized_payload,
            max_items=1,
            payload_budget_bytes=empty_size - 1,
        )
