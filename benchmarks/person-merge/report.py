"""Compare benchmark result files. First file is the baseline.

Usage:
    uv run report.py results/current-iter0.json results/union-find-iter1.json
"""

import json
import argparse
from pathlib import Path
from typing import Any


def load(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def phase_key(phase: dict[str, Any]) -> tuple:
    return (phase["case"], phase["size"], phase["concurrency"], phase["contention"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+")
    args = parser.parse_args()

    results = [load(f) for f in args.files]
    baseline = results[0]
    base_phases = {phase_key(p): p for p in baseline["phases"]}

    print(f"baseline: {baseline['strategy']} @ {baseline['git_sha']} (pg {baseline['pg_version']})")
    for result in results[1:]:
        contract = "current-contract" if result["supports_current_contract"] else "NEEDS CH CHANGE"
        print(f"candidate: {result['strategy']} @ {result['git_sha']} [{contract}]")
    print()

    header = (
        f"{'case':>8} {'size':>6} {'conc':>4} | {'strategy':>16} {'p50 ms':>10} {'p95 ms':>10} "
        f"{'wal/op':>10} {'msgs/op':>8} {'read p50':>9} | {'p50 x':>7} {'wal x':>7}"
    )
    print(header)
    print("-" * len(header))

    for key in sorted(base_phases):
        base = base_phases[key]
        rows = [(baseline["strategy"], base)]
        for result in results[1:]:
            match = next((p for p in result["phases"] if phase_key(p) == key), None)
            if match:
                rows.append((result["strategy"], match))
        for name, p in rows:
            msgs = p["emissions_per_op"]["current_contract"] + p["emissions_per_op"]["new_contract"]
            p50x = p["latency_ms"]["p50"] / base["latency_ms"]["p50"] if base["latency_ms"]["p50"] else float("nan")
            walx = p["wal_bytes_per_op"] / base["wal_bytes_per_op"] if base["wal_bytes_per_op"] else float("nan")
            print(
                f"{p['case']:>8} {p['size']:>6} {p['concurrency']:>4} | {name:>16} "
                f"{p['latency_ms']['p50']:>10.3f} {p['latency_ms']['p95']:>10.3f} "
                f"{p['wal_bytes_per_op']:>10} {msgs:>8.1f} {p['read_latency_ms']['p50']:>9.4f} | "
                f"{p50x:>6.2f}x {walx:>6.2f}x"
            )
        print()


if __name__ == "__main__":
    main()
