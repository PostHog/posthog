"""Synthetic event generator (DEMO ONLY).

This is a standalone, self-contained demonstration script. It generates
fake product-analytics events so that a PR can be shown end-to-end. None of
the data is real and nothing here is wired into the PostHog application.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

# Deterministic pseudo-randomness so the output is reproducible without
# pulling in any real user data or external services.
_SEED = 42

EVENTS = ["$pageview", "signed_up", "created_project", "invited_teammate", "upgraded_plan"]
COUNTRIES = ["US", "GB", "DE", "IN", "BR", "AU"]
PLANS = ["free", "scale", "enterprise"]


def _lcg(seed: int):
    """Tiny linear-congruential generator for repeatable demo values."""
    value = seed
    while True:
        value = (1103515245 * value + 12345) % (2**31)
        yield value


@dataclass
class SyntheticEvent:
    distinct_id: str
    event: str
    country: str
    plan: str
    properties: dict = field(default_factory=dict)


def generate(n: int = 50) -> list[SyntheticEvent]:
    rng = _lcg(_SEED)
    events: list[SyntheticEvent] = []
    for i in range(n):
        events.append(
            SyntheticEvent(
                distinct_id=f"user_{next(rng) % 1000:04d}",
                event=EVENTS[next(rng) % len(EVENTS)],
                country=COUNTRIES[next(rng) % len(COUNTRIES)],
                plan=PLANS[next(rng) % len(PLANS)],
                properties={"session_index": i, "is_demo": True},
            )
        )
    return events


def write_csv(events: list[SyntheticEvent], path: Path) -> None:
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["distinct_id", "event", "country", "plan", "properties"])
        for e in events:
            writer.writerow([e.distinct_id, e.event, e.country, e.plan, json.dumps(e.properties)])


if __name__ == "__main__":
    out = generate()
    target = Path(__file__).parent / "sample_events.csv"
    write_csv(out, target)
    print(f"Wrote {len(out)} synthetic events to {target}")
