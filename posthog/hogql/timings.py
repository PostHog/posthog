from dataclasses import dataclass, field
from time import perf_counter
from typing import Dict, List
from contextlib import contextmanager

from posthog.schema import QueryTiming


@dataclass
class HogQLTimings:
    # Timings in seconds for different parts of the HogQL query
    timings: Dict[str, float] = field(default_factory=dict)
    # Used for housekeeping
    timing_starts: Dict[str, float] = field(default_factory=dict)
    # Used for housekeeping
    timing_pointer: str = "."

    def __post_init__(self):
        self.timing_starts["."] = perf_counter()

    @contextmanager
    def measure(self, key: str):
        last_key = self.timing_pointer
        full_key = f"{self.timing_pointer}/{key}"
        self.timing_pointer = full_key
        self.timing_starts[full_key] = perf_counter()
        try:
            yield
        finally:
            self.timings[full_key] = self.timings.get(full_key, 0.0) + (perf_counter() - self.timing_starts[full_key])
            del self.timing_starts[full_key]
            self.timing_pointer = last_key

    def to_dict(self) -> Dict[str, float]:
        timings = {**self.timings}
        for key, start in self.timing_starts.items():
            timings[key] = timings.get(key, 0.0) + (perf_counter() - start)
        return timings

    def to_list(self) -> List[QueryTiming]:
        timings = {**self.timings}
        for key, start in reversed(self.timing_starts.items()):
            timings[key] = timings.get(key, 0.0) + (perf_counter() - start)
        return [QueryTiming(k=key, t=time) for key, time in timings.items()]
