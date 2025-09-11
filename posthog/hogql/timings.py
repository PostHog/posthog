from contextlib import contextmanager
from time import perf_counter

from posthog.schema import QueryTiming


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
    def measure(self, key: str):
        last_key = self._timing_pointer
        full_key = f"{self._timing_pointer}/{key}"
        self._timing_pointer = full_key
        self._timing_starts[full_key] = perf_counter()
        try:
            yield
        finally:
            duration = perf_counter() - self._timing_starts[full_key]
            self.timings[full_key] = self.timings.get(full_key, 0.0) + duration
            del self._timing_starts[full_key]
            self._timing_pointer = last_key

    def to_dict(self) -> dict[str, float]:
        timings = {**self.timings}
        for key, start in reversed(self._timing_starts.items()):
            timings[key] = timings.get(key, 0.0) + (perf_counter() - start)
        return timings

    def to_list(self, back_out_stack=True) -> list[QueryTiming]:
        return [
            QueryTiming(k=key, t=time) for key, time in (self.to_dict() if back_out_stack else self.timings).items()
        ]
