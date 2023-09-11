from dataclasses import dataclass, field
from time import perf_counter
from typing import Dict, List
from contextlib import contextmanager

from sentry_sdk import start_span

from posthog.schema import QueryTiming


@dataclass
class HogQLTimings:
    # Completed time in seconds for different parts of the HogQL query
    timings: Dict[str, float] = field(default_factory=dict)

    # Used for housekeeping
    _timing_starts: Dict[str, float] = field(default_factory=dict)
    _timing_pointer: str = "."

    def __post_init__(self):
        self._timing_starts["."] = perf_counter()

    @contextmanager
    def measure(self, key: str):
        last_key = self._timing_pointer
        full_key = f"{self._timing_pointer}/{key}"
        self._timing_pointer = full_key
        self._timing_starts[full_key] = perf_counter()
        try:
            with start_span(op=key) as span:
                yield
        finally:
            duration = perf_counter() - self._timing_starts[full_key]
            self.timings[full_key] = self.timings.get(full_key, 0.0) + duration
            del self._timing_starts[full_key]
            self._timing_pointer = last_key
            if span:
                span.set_tag("duration_seconds", duration)

    def to_dict(self) -> Dict[str, float]:
        timings = {**self.timings}
        for key, start in reversed(self._timing_starts.items()):
            timings[key] = timings.get(key, 0.0) + (perf_counter() - start)
        return timings

    def to_list(self) -> List[QueryTiming]:
        return [QueryTiming(k=key, t=time) for key, time in self.to_dict().items()]
