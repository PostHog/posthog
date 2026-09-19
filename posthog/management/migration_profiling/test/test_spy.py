"""Test the py-spy raw parser and sample aggregator."""

from __future__ import annotations

from pathlib import Path

from posthog.management.migration_profiling.spy import aggregate_samples, parse_raw


def _write(path: Path, lines: list[str]) -> Path:
    path.write_text("\n".join(lines))
    return path


def test_parse_raw_skips_header_lines(tmp_path: Path) -> None:
    raw = _write(
        tmp_path / "samples.raw",
        [
            "some header",
            "frame_a;frame_b 10",
            "frame_a;frame_b;frame_c 5",
            "",
            "ignore this without count",
            "frame_x 3",
        ],
    )
    samples = parse_raw(raw)
    assert (["frame_a", "frame_b"], 10) in samples
    assert (["frame_a", "frame_b", "frame_c"], 5) in samples
    assert (["frame_x"], 3) in samples
    assert len(samples) == 3


def test_parse_raw_normalizes_line_numbers(tmp_path: Path) -> None:
    raw = _write(
        tmp_path / "samples.raw",
        [
            "mod:func:10 5",
            "mod:func:42 3",
        ],
    )
    samples = parse_raw(raw)
    # Both stacks normalize to the same single-frame stack.
    assert all(s[0] == ["mod:func"] for s in samples)


def test_aggregate_self_and_cumulative() -> None:
    samples = [
        (["main", "a", "b"], 4),
        (["main", "a"], 6),
        (["main", "c", "b"], 2),
    ]
    agg = aggregate_samples(samples, top_n=10)

    self_by_fn = {fn: n for fn, n, _ in agg.by_self}
    cum_by_fn = {fn: n for fn, n, _ in agg.by_cumulative}

    # Leaf frames only count toward self-time.
    assert self_by_fn["b"] == 6  # 4 + 2
    assert self_by_fn["a"] == 6
    assert "main" not in self_by_fn or self_by_fn.get("main", 0) == 0

    # Cumulative: every unique frame in the stack contributes.
    assert cum_by_fn["main"] == 12
    assert cum_by_fn["a"] == 10
    assert cum_by_fn["b"] == 6
    assert cum_by_fn["c"] == 2

    assert agg.total_samples == 12


def test_aggregate_empty() -> None:
    agg = aggregate_samples([])
    assert agg.total_samples == 0
    assert agg.by_self == []
    assert agg.by_cumulative == []
