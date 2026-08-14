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


def read_p50(phase: dict[str, Any]) -> float:
    detail = phase.get("read_latency_detail_ms")
    if detail and "merged" in detail:
        return detail["merged"]["p50"]
    return phase["read_latency_ms"]["p50"]


def print_merge_phases(results: list[dict[str, Any]]) -> None:
    baseline = results[0]
    base_phases = {phase_key(p): p for p in baseline["phases"] if "steps" not in p}
    if not base_phases:
        return

    header = (
        f"{'case':>8} {'size':>6} {'conc':>4} | {'strategy':>22} {'p50 ms':>10} {'p95 ms':>10} "
        f"{'wal/op':>10} {'msgs/op':>8} {'read p50':>9} | {'p50 x':>7} {'wal x':>7}"
    )
    print(header)
    print("-" * len(header))

    for key in sorted(base_phases):
        base = base_phases[key]
        rows = [(baseline["strategy"], base)]
        for result in results[1:]:
            match = next((p for p in result["phases"] if "steps" not in p and phase_key(p) == key), None)
            if match:
                rows.append((result["strategy"], match))
        for name, p in rows:
            msgs = p["emissions_per_op"]["current_contract"] + p["emissions_per_op"]["new_contract"]
            p50x = p["latency_ms"]["p50"] / base["latency_ms"]["p50"] if base["latency_ms"]["p50"] else float("nan")
            walx = p["wal_bytes_per_op"] / base["wal_bytes_per_op"] if base["wal_bytes_per_op"] else float("nan")
            print(
                f"{p['case']:>8} {p['size']:>6} {p['concurrency']:>4} | {name:>22} "
                f"{p['latency_ms']['p50']:>10.3f} {p['latency_ms']['p95']:>10.3f} "
                f"{p['wal_bytes_per_op']:>10} {msgs:>8.1f} {read_p50(p):>9.4f} | "
                f"{p50x:>6.2f}x {walx:>6.2f}x"
            )
        print()


def print_chain_phases(results: list[dict[str, Any]]) -> None:
    chain_rows: list[tuple[str, dict[str, Any]]] = [
        (result["strategy"], p) for result in results for p in result["phases"] if "steps" in p
    ]
    if not chain_rows:
        return

    print("chain workload (repeated re-merging; read = resolve through the full chain)")
    header = (
        f"{'dids':>6} {'depth':>5} | {'strategy':>22} {'merge p50':>10} {'read p50':>9} "
        f"{'read p95':>9} {'wal/op':>10} {'msgs/op':>8}"
    )
    print(header)
    print("-" * len(header))
    sizes = sorted({p["size"] for _, p in chain_rows})
    for size in sizes:
        depths = sorted({s["depth"] for _, p in chain_rows if p["size"] == size for s in p["steps"]})
        for depth in depths:
            for name, p in chain_rows:
                if p["size"] != size:
                    continue
                step = next((s for s in p["steps"] if s["depth"] == depth), None)
                if step is None:
                    continue
                print(
                    f"{size:>6} {depth:>5} | {name:>22} {step['merge_p50_ms']:>10.3f} "
                    f"{step['read_p50_ms']:>9.4f} {step['read_p95_ms']:>9.4f} "
                    f"{step['wal_bytes_per_op']:>10} {step['msgs_per_op']:>8.1f}"
                )
            print()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+")
    args = parser.parse_args()

    results = [load(f) for f in args.files]
    baseline = results[0]

    print(f"baseline: {baseline['strategy']} @ {baseline['git_sha']} (pg {baseline['pg_version']})")
    for result in results[1:]:
        contract = "current-contract" if result["supports_current_contract"] else "NEEDS CH CHANGE"
        print(f"candidate: {result['strategy']} @ {result['git_sha']} [{contract}]")
    print()

    print_merge_phases(results)
    print_chain_phases(results)


if __name__ == "__main__":
    main()
