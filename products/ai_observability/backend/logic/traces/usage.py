import math
from collections.abc import Iterable, Sequence
from typing import TypeVar

from posthog.dataclasses import frozen

Number = TypeVar("Number", int, float)


def sum_known(values: Iterable[Number | None]) -> Number | None:
    known = [value for value in values if value is not None]
    return sum(known) if known else None


@frozen
class Usage:
    cost_usd: float | None = None
    latency_s: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None

    def rolled_up(self, parts: Sequence["Usage"]) -> "Usage":
        # A sum over parts that never reported a cost stays unknown, because $0.00 would read as a free call.
        # Latency and tokens count a silent part as zero. Cache tokens are only ever the node's own.
        return Usage(
            cost_usd=self.cost_usd if self.cost_usd is not None else sum_known(part.cost_usd for part in parts),
            latency_s=self.latency_s if self.latency_s is not None else sum(part.latency_s or 0 for part in parts),
            input_tokens=self.input_tokens
            if self.input_tokens is not None
            else sum(part.input_tokens or 0 for part in parts),
            output_tokens=self.output_tokens
            if self.output_tokens is not None
            else sum(part.output_tokens or 0 for part in parts),
            cache_read_tokens=self.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens,
        )

    @property
    def latency_ms(self) -> float | None:
        if self.latency_s is None:
            return None
        milliseconds = self.latency_s * 1000
        return milliseconds if math.isfinite(milliseconds) and milliseconds > 0 else None
