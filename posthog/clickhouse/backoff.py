from typing import Optional

from posthog.dataclasses import frozen


@frozen
class ExponentialBackoff:
    delay: float
    max_delay: Optional[float] = None
    exp: float = 2.0

    def __call__(self, attempt: int) -> float:
        delay = self.delay * (attempt**self.exp)
        return min(delay, self.max_delay) if self.max_delay is not None else delay
