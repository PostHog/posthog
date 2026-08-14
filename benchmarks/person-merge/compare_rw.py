"""Read/write comparison across strategies, one row per (case, size).

Usage:
    uv run compare_rw.py results/*-full-iter3.json
"""

import json
import argparse
from pathlib import Path
from typing import Any


def load(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def fmt_bytes(n: float) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}MB"
    if n >= 1_000:
        return f"{n / 1_000:.1f}KB"
    return f"{n:.0f}B"


def read_stats(phase: dict[str, Any]) -> dict[str, float]:
    detail = phase.get("read_latency_detail_ms", {})
    merged = detail.get("merged") or detail.get("target") or {}
    control = detail.get("control") or {}
    return {
        "merged_p50": merged.get("p50", phase["read_latency_ms"]["p50"]),
        "merged_p99": merged.get("p99", float("nan")),
        "control_p50": control.get("p50", float("nan")),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+")
    args = parser.parse_args()

    results = [load(f) for f in args.files]
    keys = sorted(
        {(p["case"], p["size"]) for r in results for p in r["phases"] if "steps" not in p},
        key=lambda k: (k[0], k[1]),
    )

    print("WRITE side (the merge itself)")
    header = (
        f"{'case':>8} {'size':>6} | {'strategy':>22} {'merge p50':>10} {'merge p95':>10} {'WAL/op':>9} {'msgs/op':>8}"
    )
    print(header)
    print("-" * len(header))
    for case, size in keys:
        for r in results:
            p = next((p for p in r["phases"] if "steps" not in p and p["case"] == case and p["size"] == size), None)
            if p is None:
                continue
            msgs = p["emissions_per_op"]["current_contract"] + p["emissions_per_op"]["new_contract"]
            print(
                f"{case:>8} {size:>6} | {r['strategy']:>22} {p['latency_ms']['p50']:>8.2f}ms "
                f"{p['latency_ms']['p95']:>8.2f}ms {fmt_bytes(p['wal_bytes_per_op']):>9} {msgs:>8.0f}"
            )
        print()

    print("READ side (resolve distinct id -> person, the per-event hot path)")
    header = f"{'case':>8} {'size':>6} | {'strategy':>22} {'merged p50':>10} {'merged p99':>10} {'control p50':>11}"
    print(header)
    print("-" * len(header))
    for case, size in keys:
        for r in results:
            p = next((p for p in r["phases"] if "steps" not in p and p["case"] == case and p["size"] == size), None)
            if p is None:
                continue
            s = read_stats(p)
            print(
                f"{case:>8} {size:>6} | {r['strategy']:>22} {s['merged_p50']:>8.3f}ms "
                f"{s['merged_p99']:>8.3f}ms {s['control_p50']:>9.3f}ms"
            )
        print()


if __name__ == "__main__":
    main()
