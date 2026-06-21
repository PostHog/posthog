from contextlib import contextmanager, nullcontext
from time import perf_counter
from typing import TYPE_CHECKING

from opentelemetry import trace

if TYPE_CHECKING:
    from posthog.schema import QueryTiming

_tracer = trace.get_tracer(__name__)

TIMING_DECIMAL_PLACES = 3  # round to milliseconds


# Not thread safe.
# See trends_query_runner for an example of how to use for multithreaded queries
class HogQLTimings:
    timings: dict[str, float]
    _timing_starts: dict[str, float]
    _timing_pointer: str

    def __init__(self, _timing_pointer: str = "."):
        # Completed time in seconds for different parts of the HogQL query
        self.timings = {}

        # Used for housekeeping
        self._timing_pointer = _timing_pointer
        self._timing_starts = {self._timing_pointer: perf_counter()}

    def clone_for_subquery(self, series_index: int):
        return HogQLTimings(f"{self._timing_pointer}/series_{series_index}")

    def clear_timings(self):
        self.timings = {}

    @contextmanager
    def measure(self, key: str, emit_span: bool = False):
        last_key = self._timing_pointer
        full_key = f"{self._timing_pointer}/{key}"
        self._timing_pointer = full_key
        self._timing_starts[full_key] = perf_counter()
        span_cm = _tracer.start_as_current_span(key) if emit_span else nullcontext()
        try:
            with span_cm:
                yield
        finally:
            duration = perf_counter() - self._timing_starts[full_key]
            self.timings[full_key] = self.timings.get(full_key, 0.0) + duration
            del self._timing_starts[full_key]
            self._timing_pointer = last_key

    def to_dict(self) -> dict[str, float]:
        timings = {**self.timings}
        for key, start in reversed(self._timing_starts.items()):
            timings[key] = round(timings.get(key, 0.0) + (perf_counter() - start), TIMING_DECIMAL_PLACES)
        return timings

    def to_list(self, back_out_stack=True) -> list["QueryTiming"]:
        # Deferred: posthog.schema stays off django.setup(); this module loads there via
        # hogql.context.
        from posthog.schema import QueryTiming  # noqa: PLC0415

        return [
            QueryTiming(k=key, t=round(time, TIMING_DECIMAL_PLACES))
            for key, time in (self.to_dict() if back_out_stack else self.timings).items()
        ]
