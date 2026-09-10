from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

from temporalio.converter import DataConverter

MAX_SCHEDULER_PAYLOAD_BYTES = 512 * 1024

ItemT = TypeVar("ItemT")
PayloadLimit = Literal["none", "item_limit", "byte_limit"]


@dataclass(frozen=True)
class PayloadSelection(Generic[ItemT]):
    items: tuple[ItemT, ...]
    encoded_size_bytes: int
    limited_by: PayloadLimit


async def temporal_payload_size_bytes(value: object, *, data_converter: DataConverter = DataConverter.default) -> int:
    payloads = await data_converter.encode([value])
    return sum(payload.ByteSize() for payload in payloads)


async def select_items_within_temporal_payload(
    items: Sequence[ItemT],
    *,
    build_payload: Callable[[Sequence[ItemT]], object],
    max_items: int,
    payload_budget_bytes: int = MAX_SCHEDULER_PAYLOAD_BYTES,
    data_converter: DataConverter = DataConverter.default,
) -> PayloadSelection[ItemT]:
    """Select an ordered prefix whose measured Temporal wire payload fits the hard budget.

    The binary search relies on encoded prefix size normally being non-decreasing. Custom codecs
    can violate that assumption, so callers must treat this as a safe bounded prefix rather than a
    mathematical guarantee that no larger prefix could fit. The returned prefix is always measured
    directly before it is returned.
    """

    if max_items <= 0:
        raise ValueError("max_items must be greater than zero")
    if payload_budget_bytes <= 0:
        raise ValueError("payload_budget_bytes must be greater than zero")
    if payload_budget_bytes > MAX_SCHEDULER_PAYLOAD_BYTES:
        raise ValueError(f"payload_budget_bytes exceeds the hard maximum of {MAX_SCHEDULER_PAYLOAD_BYTES} bytes")

    candidates = tuple(items[:max_items])
    encoded_sizes: dict[int, int] = {}

    async def size_for(count: int) -> int:
        if count not in encoded_sizes:
            encoded_sizes[count] = await temporal_payload_size_bytes(
                build_payload(candidates[:count]), data_converter=data_converter
            )
        return encoded_sizes[count]

    empty_size = await size_for(0)
    if empty_size > payload_budget_bytes:
        raise ValueError(
            f"fixed payload envelope is {empty_size} bytes and exceeds the {payload_budget_bytes}-byte budget"
        )

    candidate_size = await size_for(len(candidates))
    if candidate_size <= payload_budget_bytes:
        limited_by: PayloadLimit = "item_limit" if len(items) > len(candidates) else "none"
        return PayloadSelection(items=candidates, encoded_size_bytes=candidate_size, limited_by=limited_by)

    lower = 0
    upper = len(candidates)
    while lower < upper:
        midpoint = (lower + upper + 1) // 2
        if await size_for(midpoint) <= payload_budget_bytes:
            lower = midpoint
        else:
            upper = midpoint - 1

    return PayloadSelection(
        items=candidates[:lower],
        encoded_size_bytes=await size_for(lower),
        limited_by="byte_limit",
    )
