"""Benchmark runner.

Usage:
    uv run bench.py --strategy current --cases neither,one,both \
        --sizes 1,10,100,1000,10000 --reps 20 --out results/current-iter0.json

Each (case, size) phase:
  1. seeds all reps up front (seeding never pollutes timings),
  2. CHECKPOINTs to stabilize WAL/buffer state,
  3. runs the identify calls (optionally across threads, optionally all
     against one shared target person to model contention),
  4. verifies every rep against the oracle,
  5. times the strategy's read path over the merged distinct ids.

Metrics per phase: per-op wall latency, phase WAL bytes (insert LSN delta),
emissions by contract, internal retries, read-path latency.
"""

import json
import time
import argparse
import statistics
import subprocess
import concurrent.futures
from pathlib import Path
from typing import Any

import oracle
import psycopg
import workload
from strategies.base import MergeOutcome, Strategy
from strategies.current import CurrentStrategy
from strategies.union_find import UnionFindCompatStrategy, UnionFindCompressedStrategy, UnionFindStrategy

DSN_DEFAULT = "host=127.0.0.1 port=5544 user=posthog dbname=merge_bench"

STRATEGIES: dict[str, type] = {
    "current": CurrentStrategy,
    "union_find": UnionFindStrategy,
    "union_find_compat": UnionFindCompatStrategy,
    "union_find_compressed": UnionFindCompressedStrategy,
}


def get_strategy(name: str) -> Strategy:
    try:
        return STRATEGIES[name]()
    except KeyError:
        raise SystemExit(f"unknown strategy {name!r}; known: {sorted(STRATEGIES)}")


def fresh_database(dsn: str, strategy: Strategy, preload_persons: int) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    with psycopg.connect(dsn) as conn:
        for schema_file in strategy.schema_files():
            conn.execute(Path(schema_file).read_text())
        conn.commit()
        workload.preload(conn, persons=preload_persons)
        conn.commit()
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("VACUUM ANALYZE")
        conn.execute("CHECKPOINT")


def wal_lsn(conn: psycopg.Connection) -> int:
    return conn.execute("SELECT pg_current_wal_insert_lsn() - '0/0'::pg_lsn").fetchone()[0]


def run_phase(
    dsn: str,
    strategy: Strategy,
    case: str,
    size: int,
    reps: int,
    concurrency: int,
    contention: str,
) -> dict[str, Any]:
    seed_conn = psycopg.connect(dsn)
    tag_base = f"{case}-{size}-{time.monotonic_ns()}"

    shared_target: str | None = None
    if contention == "shared-target":
        if case != "both":
            raise SystemExit("--contention shared-target only applies to the 'both' case")
        # One target person; every rep merges a fresh source into it.
        shared = workload.seed_case(seed_conn, "one", 0, f"{tag_base}-shared")
        shared_target = shared.target_distinct_id
        # Materialize the target person via the strategy itself so the merge
        # sees an existing person for the shared target's distinct id.

    seeded: list[workload.SeededCase] = []
    for rep in range(reps):
        sc = workload.seed_case(seed_conn, case, size, f"{tag_base}-{rep}")
        if shared_target is not None:
            sc = workload.SeededCase(
                case=sc.case,
                target_distinct_id=shared_target,
                anon_distinct_id=sc.anon_distinct_id,
                expected_distinct_ids=[shared_target]
                + [d for d in sc.expected_distinct_ids if d != sc.target_distinct_id],
                source_did_count=sc.source_did_count,
                cohort_rows=sc.cohort_rows,
                ff_rows=sc.ff_rows,
            )
        seeded.append(sc)

    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute("CHECKPOINT")

    wal_before = wal_lsn(seed_conn)
    outcomes: list[MergeOutcome | None] = [None] * reps
    latencies_ms: list[float] = [0.0] * reps

    def run_one(idx: int, conn: psycopg.Connection) -> None:
        sc = seeded[idx]
        t0 = time.perf_counter()
        outcomes[idx] = strategy.identify(conn, workload.TEAM_ID, sc.target_distinct_id, sc.anon_distinct_id)
        latencies_ms[idx] = (time.perf_counter() - t0) * 1000

    if concurrency <= 1:
        with psycopg.connect(dsn) as conn:
            for i in range(reps):
                run_one(i, conn)
    else:

        def worker(indices: list[int]) -> None:
            with psycopg.connect(dsn) as conn:
                for i in indices:
                    run_one(i, conn)

        buckets: list[list[int]] = [[] for _ in range(concurrency)]
        for i in range(reps):
            buckets[i % concurrency].append(i)
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
            list(pool.map(worker, buckets))

    wal_after = wal_lsn(seed_conn)

    # Oracle over every rep. Under shared-target contention the per-rep target
    # person changes as merges land, so only resolution/consistency checks that
    # remain valid are asserted: every distinct id must resolve to one single
    # surviving person.
    checks = 0
    if contention == "shared-target":
        survivor = strategy.resolve(seed_conn, workload.TEAM_ID, shared_target)
        assert survivor is not None, "shared target lost its person"
        for sc in seeded:
            for did in sc.expected_distinct_ids:
                r = strategy.resolve(seed_conn, workload.TEAM_ID, did)
                assert r is not None and r.person_id == survivor.person_id, (
                    f"{did!r} did not land on the shared survivor"
                )
                checks += 1
    else:
        for sc, oc in zip(seeded, outcomes):
            assert oc is not None
            checks += oracle.verify(seed_conn, strategy, sc, oc).checks

    # Read path, stratified: the target's own id, ids that arrived via the
    # merge (these exercise indirection/chains in pointer-based strategies),
    # and untouched preload ids as the control.
    target_sample = [sc.target_distinct_id for sc in seeded][:500]
    merged_sample = [did for sc in seeded for did in sc.expected_distinct_ids[1:]][:500]
    with psycopg.connect(dsn) as conn:
        control_sample = [
            r[0]
            for r in conn.execute(
                "SELECT distinct_id FROM posthog_persondistinctid WHERE distinct_id LIKE 'preload-%' LIMIT 200"
            ).fetchall()
        ]

        def time_reads(dids: list[str]) -> list[float]:
            out: list[float] = []
            for did in dids:
                t0 = time.perf_counter()
                strategy.resolve(conn, workload.TEAM_ID, did)
                out.append((time.perf_counter() - t0) * 1000)
            return out

        read_by_kind = {
            "target": time_reads(target_sample),
            "merged": time_reads(merged_sample),
            "control": time_reads(control_sample),
        }
    read_latencies_ms = read_by_kind["target"] + read_by_kind["merged"]

    emissions_current = sum(sum(1 for e in oc.emissions if e.contract == "current") for oc in outcomes if oc)
    emissions_new = sum(sum(1 for e in oc.emissions if e.contract == "new") for oc in outcomes if oc)
    retries = sum(oc.retries for oc in outcomes if oc)
    seed_conn.close()

    def pct(data: list[float], q: float) -> float:
        return statistics.quantiles(data, n=100)[int(q) - 1] if len(data) >= 2 else data[0]

    return {
        "case": case,
        "size": size,
        "reps": reps,
        "concurrency": concurrency,
        "contention": contention,
        "latency_ms": {
            "p50": round(statistics.median(latencies_ms), 3),
            "p95": round(pct(latencies_ms, 95), 3),
            "max": round(max(latencies_ms), 3),
            "raw": [round(x, 3) for x in latencies_ms],
        },
        "read_latency_ms": {
            "p50": round(statistics.median(read_latencies_ms), 4),
            "p95": round(pct(read_latencies_ms, 95), 4),
        },
        "read_latency_detail_ms": {
            kind: {
                "p50": round(statistics.median(data), 4),
                "p95": round(pct(data, 95), 4),
                "p99": round(pct(data, 99), 4),
                "n": len(data),
            }
            for kind, data in read_by_kind.items()
            if data
        },
        "wal_bytes_per_op": round((wal_after - wal_before) / reps),
        "emissions_per_op": {
            "current_contract": emissions_current / reps,
            "new_contract": emissions_new / reps,
        },
        "retries_total": retries,
        "oracle_checks": checks,
    }


def run_chain_phase(
    dsn: str,
    strategy: Strategy,
    dids_per_person: int,
    depth_max: int,
    chains: int,
) -> dict[str, Any]:
    """Repeated re-merging: at each step the current survivor is merged into a
    fresh person, so the first person's distinct ids sit behind `depth` merges.

    This is the read-path stress for indirection strategies (pointer chains)
    and the write amplification stress for eager-move strategies (accumulated
    mappings get physically re-moved on every step). Models `$merge_dangerously`
    semantics: production `$identify` refuses identified sources, chained
    merges of identified persons only happen via `$merge_dangerously`.
    """
    seed_conn = psycopg.connect(dsn)
    tag_base = f"chain-{dids_per_person}-{time.monotonic_ns()}"
    chain_dids = [
        workload.seed_chain_persons(seed_conn, depth_max + 1, dids_per_person, f"{tag_base}-{c}") for c in range(chains)
    ]

    steps: list[dict[str, Any]] = []
    checks = 0
    with psycopg.connect(dsn) as merge_conn, psycopg.connect(dsn) as read_conn:
        for depth in range(1, depth_max + 1):
            wal_before = wal_lsn(seed_conn)
            merge_latencies: list[float] = []
            msgs = 0
            for c in range(chains):
                # Merge the current survivor (reachable via the first person's
                # first distinct id) into the fresh person at this depth.
                anon_did = chain_dids[c][0][0]
                target_did = chain_dids[c][depth][0]
                t0 = time.perf_counter()
                outcome = strategy.identify(merge_conn, workload.TEAM_ID, target_did, anon_did)
                merge_latencies.append((time.perf_counter() - t0) * 1000)
                msgs += len(outcome.emissions)
            wal_after = wal_lsn(seed_conn)

            # Reads through the full chain: the first person's distinct ids.
            read_latencies: list[float] = []
            for c in range(chains):
                for did in chain_dids[c][0][: min(dids_per_person, 20)]:
                    t0 = time.perf_counter()
                    resolved = strategy.resolve(read_conn, workload.TEAM_ID, did)
                    read_latencies.append((time.perf_counter() - t0) * 1000)
                    survivor = strategy.resolve(read_conn, workload.TEAM_ID, chain_dids[c][depth][0])
                    assert resolved is not None and survivor is not None
                    assert resolved.person_id == survivor.person_id, f"chain read diverged at depth {depth}: {did!r}"
                    checks += 1

            def pct(data: list[float], q: float) -> float:
                return statistics.quantiles(data, n=100)[int(q) - 1] if len(data) >= 2 else data[0]

            steps.append(
                {
                    "depth": depth,
                    "merge_p50_ms": round(statistics.median(merge_latencies), 3),
                    "merge_p95_ms": round(pct(merge_latencies, 95), 3),
                    "read_p50_ms": round(statistics.median(read_latencies), 4),
                    "read_p95_ms": round(pct(read_latencies, 95), 4),
                    "wal_bytes_per_op": round((wal_after - wal_before) / chains),
                    "msgs_per_op": round(msgs / chains, 1),
                }
            )
    seed_conn.close()

    return {
        "case": "chain",
        "size": dids_per_person,
        "reps": chains,
        "concurrency": 1,
        "contention": "none",
        "depth_max": depth_max,
        "steps": steps,
        "oracle_checks": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--cases", default="neither,one,both")
    parser.add_argument("--sizes", default="1,10,100,1000,10000", help="source distinct-id counts for the 'both' case")
    parser.add_argument("--reps", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--contention", choices=["none", "shared-target"], default="none")
    parser.add_argument("--chain-depth", type=int, default=16, help="max merge depth for the 'chain' case")
    parser.add_argument("--preload", type=int, default=workload.PRELOAD_PERSONS)
    parser.add_argument("--dsn", default=DSN_DEFAULT)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    strategy = get_strategy(args.strategy)
    fresh_database(args.dsn, strategy, args.preload)

    with psycopg.connect(args.dsn) as conn:
        pg_version = conn.execute("SHOW server_version").fetchone()[0]

    git_sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()

    phases = []
    for case in args.cases.split(","):
        sizes = [int(s) for s in args.sizes.split(",")] if case in ("both", "chain") else [0]
        for size in sizes:
            if case == "chain":
                phase = run_chain_phase(args.dsn, strategy, size, args.chain_depth, args.reps)
                phases.append(phase)
                for step in phase["steps"]:
                    print(
                        f"{strategy.name:>14} chain dids={size:<6} depth={step['depth']:<3} "
                        f"merge-p50={step['merge_p50_ms']:>9.3f}ms read-p50={step['read_p50_ms']:>8.4f}ms "
                        f"read-p95={step['read_p95_ms']:>8.4f}ms wal/op={step['wal_bytes_per_op']:>9} "
                        f"msgs/op={step['msgs_per_op']:>8.1f}"
                    )
                continue
            phase = run_phase(args.dsn, strategy, case, size, args.reps, args.concurrency, args.contention)
            phases.append(phase)
            lat = phase["latency_ms"]
            detail = phase["read_latency_detail_ms"]
            merged_read = detail.get("merged", detail.get("target", {"p50": float("nan")}))
            print(
                f"{strategy.name:>14} {case:>8} size={size:<6} p50={lat['p50']:>9.3f}ms "
                f"p95={lat['p95']:>9.3f}ms wal/op={phase['wal_bytes_per_op']:>9} "
                f"msgs/op={phase['emissions_per_op']['current_contract'] + phase['emissions_per_op']['new_contract']:>8.1f} "
                f"read-merged-p50={merged_read['p50']:.4f}ms oracle-checks={phase['oracle_checks']}"
            )

    result = {
        "strategy": strategy.name,
        "supports_current_contract": strategy.supports_current_contract,
        "git_sha": git_sha,
        "pg_version": pg_version,
        "args": {k: v for k, v in vars(args).items() if k != "dsn"},
        "phases": phases,
    }
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=2) + "\n")
        print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
