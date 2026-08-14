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

DSN_DEFAULT = "host=127.0.0.1 port=5544 user=posthog dbname=merge_bench"

STRATEGIES: dict[str, type] = {
    "current": CurrentStrategy,
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

    # Read path: resolve a sample of merged distinct ids.
    read_sample = [did for sc in seeded for did in sc.expected_distinct_ids][:500]
    read_latencies_ms: list[float] = []
    with psycopg.connect(dsn) as conn:
        for did in read_sample:
            t0 = time.perf_counter()
            strategy.resolve(conn, workload.TEAM_ID, did)
            read_latencies_ms.append((time.perf_counter() - t0) * 1000)

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
        "wal_bytes_per_op": round((wal_after - wal_before) / reps),
        "emissions_per_op": {
            "current_contract": emissions_current / reps,
            "new_contract": emissions_new / reps,
        },
        "retries_total": retries,
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
        sizes = [int(s) for s in args.sizes.split(",")] if case == "both" else [0]
        for size in sizes:
            phase = run_phase(args.dsn, strategy, case, size, args.reps, args.concurrency, args.contention)
            phases.append(phase)
            lat = phase["latency_ms"]
            print(
                f"{strategy.name:>14} {case:>8} size={size:<6} p50={lat['p50']:>9.3f}ms "
                f"p95={lat['p95']:>9.3f}ms wal/op={phase['wal_bytes_per_op']:>9} "
                f"msgs/op={phase['emissions_per_op']['current_contract'] + phase['emissions_per_op']['new_contract']:>8.1f} "
                f"read-p50={phase['read_latency_ms']['p50']:.4f}ms oracle-checks={phase['oracle_checks']}"
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
