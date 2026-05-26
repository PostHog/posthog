"""Parser for pyinstrument's JSON output.

Pyinstrument dumps a recursive frame tree where each node has:

    {
      "function": "Migration.apply",
      "file_path_short": "django/db/migrations/migration.py",
      "line_no": 94,
      "time": 12.3,          # cumulative seconds in this frame and children
      "await_time": 0,
      "children": [...]
    }

We walk it to build per-function aggregates:

- ``self_time``: time spent in this frame minus time spent in its children
  (the "self" cost of the function).
- ``cumulative_time``: the raw ``time`` field summed across all instances of
  the function in the tree.

Functions are identified by ``module:function`` (line number stripped) so
the same function called from different parents aggregates.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class PyinstrumentAggregate:
    total_duration_s: float
    sample_count: int | None
    by_self: list[tuple[str, float, float]]  # (function, self_s, self_pct)
    by_cumulative: list[tuple[str, float, float]]  # (function, cumulative_s, pct)


def _frame_key(frame: dict[str, Any]) -> str:
    func = frame.get("function", "<unknown>")
    file_short = frame.get("file_path_short") or frame.get("file_path", "")
    if file_short:
        return f"{file_short}:{func}"
    return func


def _walk(
    frame: dict[str, Any],
    self_times: dict[str, float],
    cum_times: dict[str, float],
) -> None:
    children = frame.get("children") or []
    total_time = frame.get("time", 0.0)
    children_time = sum(c.get("time", 0.0) for c in children)
    self_time = max(total_time - children_time, 0.0)

    key = _frame_key(frame)
    self_times[key] += self_time
    cum_times[key] += total_time

    for child in children:
        _walk(child, self_times, cum_times)


def parse_pyinstrument_json(path: Path, top_n: int = 30) -> PyinstrumentAggregate:
    payload = json.loads(path.read_text())
    root = payload.get("root_frame") or {}
    self_times: dict[str, float] = defaultdict(float)
    cum_times: dict[str, float] = defaultdict(float)
    _walk(root, self_times, cum_times)

    total_duration = payload.get("duration") or root.get("time", 0.0)
    sample_count = payload.get("sample_count")

    def _top(d: dict[str, float]) -> list[tuple[str, float, float]]:
        rows = sorted(d.items(), key=lambda x: -x[1])[:top_n]
        if total_duration > 0:
            return [(fn, t, (t / total_duration) * 100.0) for fn, t in rows]
        return [(fn, t, 0.0) for fn, t in rows]

    return PyinstrumentAggregate(
        total_duration_s=total_duration,
        sample_count=sample_count,
        by_self=_top(self_times),
        by_cumulative=_top(cum_times),
    )
