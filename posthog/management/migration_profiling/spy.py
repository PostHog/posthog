"""py-spy raw-format parser and aggregator.

``py-spy record --format raw`` emits one line per unique stack:
``frame1;frame2;...;frameN <count>`` where each frame is
``module:function:line``. Lines beginning with non-digit / non-frame syntax
are header noise we ignore.

We use the parsed samples for two things:

1. A top-N by self-time / cumulative-time table inserted into the Markdown
   report (driven from ``aggregate_samples``).
2. A flame-graph SVG rendered via the ``flameprof`` package. We feed the raw
   collapsed-stack file through ``flameprof.render`` as-is — no preprocessing
   needed.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FunctionStats:
    function: str
    self_samples: int
    cum_samples: int

    @property
    def self_pct(self) -> float:
        return 0.0  # filled by aggregator using total samples

    @property
    def cum_pct(self) -> float:
        return 0.0


@dataclass
class SpyAggregate:
    total_samples: int
    by_self: list[tuple[str, int, float]]  # (function, self_samples, self_pct)
    by_cumulative: list[tuple[str, int, float]]  # (function, cum_samples, cum_pct)


def _normalize_frame(frame: str) -> str:
    """Strip the line-number component so ``mod:func:123`` aggregates with
    ``mod:func:456`` (both are the same function). Leaves frames that don't
    match the expected shape unchanged."""
    parts = frame.rsplit(":", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return parts[0]
    return frame


def parse_raw(path: Path) -> list[tuple[list[str], int]]:
    """Read a py-spy ``--format raw`` file. Returns list of
    ``(frames, sample_count)`` tuples."""
    samples: list[tuple[list[str], int]] = []
    with open(path) as fp:
        for raw_line in fp:
            line = raw_line.strip()
            if not line:
                continue
            # The last whitespace-separated token must be a positive integer
            # sample count for it to be a sample line.
            try:
                stack_part, count_part = line.rsplit(" ", 1)
                count = int(count_part)
            except ValueError:
                continue
            if count <= 0:
                continue
            frames = [_normalize_frame(f) for f in stack_part.split(";") if f]
            if not frames:
                continue
            samples.append((frames, count))
    return samples


def aggregate_samples(samples: list[tuple[list[str], int]], top_n: int = 30) -> SpyAggregate:
    self_counts: dict[str, int] = defaultdict(int)
    cum_counts: dict[str, int] = defaultdict(int)
    total = 0

    for frames, count in samples:
        total += count
        # Self-time: only the leaf (last) frame.
        self_counts[frames[-1]] += count
        # Cumulative: every unique frame in this stack contributes once.
        for frame in set(frames):
            cum_counts[frame] += count

    def _top(counts: dict[str, int]) -> list[tuple[str, int, float]]:
        pct = 100.0 / total if total else 0.0
        return sorted(
            ((fn, n, n * pct) for fn, n in counts.items()),
            key=lambda x: x[1],
            reverse=True,
        )[:top_n]

    return SpyAggregate(total_samples=total, by_self=_top(self_counts), by_cumulative=_top(cum_counts))


def render_flame_svg(raw_path: Path, svg_path: Path) -> bool:
    """Render an SVG flame graph from a py-spy raw file.

    Returns True on success, False if ``flameprof`` isn't installed or fails.
    Failure is non-fatal — the analyze command continues without the SVG.
    """
    try:
        import flameprof
    except ImportError:
        return False

    try:
        svg_path.parent.mkdir(parents=True, exist_ok=True)
        with open(raw_path) as fin, open(svg_path, "w") as fout:
            flameprof.render(fin, fout)
        return True
    except Exception:
        return False
