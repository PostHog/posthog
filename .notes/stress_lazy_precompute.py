"""
Local stress test for PR #59075 (web_overview_query lazy precompute).

Fires N concurrent web_overview_query requests against the same
(team, host filter, window) tuple and validates:

  1. Postgres: exactly one analytics_platform_preaggregationjob row per
     (team_id, query_hash, time_range) — IntegrityError on the partial
     unique index prevents duplicates.

  2. ClickHouse `web_overview_preaggregated` FINAL: exactly one row per
     (team_id, time_window_start, job_id) — no double-INSERT artifacts.

  3. All N response payloads are byte-identical — no race-induced
     divergence between concurrent first-readers.

Pre-reqs (run once before this script):
  hogli docker:services:up && hogli migrations:run
  hogli dev:demo-data -y                   # produces a hedgebox team
  python .notes/stress_lazy_precompute.py  # this file

Usage:
  python .notes/stress_lazy_precompute.py --team-id <id> --concurrency 10
"""

import argparse
import json
import os
import sys
import threading
import time
from datetime import UTC, datetime, timedelta

# Allow running directly from repo root: ./.notes/stress_lazy_precompute.py
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")

import django

django.setup()

from posthog.clickhouse.client import sync_execute  # noqa: E402
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries, tags_context  # noqa: E402
from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner  # noqa: E402
from posthog.models import Team  # noqa: E402
from posthog.models.instance_setting import set_instance_setting  # noqa: E402
from posthog.schema import (  # noqa: E402
    DateRange,
    EventPropertyFilter,
    PropertyOperator,
    WebOverviewQuery,
)
from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob  # noqa: E402


def build_query(host: str, date_from: str, date_to: str) -> WebOverviewQuery:
    return WebOverviewQuery(
        dateRange=DateRange(date_from=date_from, date_to=date_to),
        properties=[
            EventPropertyFilter(key="$host", operator=PropertyOperator.EXACT, value=host),
        ],
    )


def pick_top_host(team: Team) -> str | None:
    """Find the most common $host in the team's recent events."""
    rows = sync_execute(
        """
        SELECT JSONExtractString(properties, '$host') AS host, count() AS c
        FROM events
        WHERE team_id = %(team_id)s
          AND event = '$pageview'
          AND timestamp > now() - INTERVAL 30 DAY
          AND host != ''
        GROUP BY host
        ORDER BY c DESC
        LIMIT 1
        """,
        {"team_id": team.pk},
    )
    return rows[0][0] if rows else None


def fire_one(team: Team, host: str, date_from: str, date_to: str, results: list, idx: int):
    # tags_context is contextvar-based and doesn't propagate to plain threads.
    tag_queries(product=Product.WEB_ANALYTICS, feature=Feature.QUERY, team_id=team.pk)
    print(f"  [thread {idx:02d}] start @ {time.monotonic():.4f}", flush=True)
    query = build_query(host, date_from, date_to)
    runner = WebOverviewQueryRunner(query=query, team=team)
    t0 = time.monotonic()
    try:
        response = runner._calculate()
        elapsed_ms = (time.monotonic() - t0) * 1000
        used_preagg = bool(getattr(response, "usedPreAggregatedTables", False))
        # Normalize results to compare across threads.
        payload = [
            {"key": r.key, "value": r.value, "previous": r.previous}
            for r in (response.results or [])
        ]
        results[idx] = {
            "ok": True,
            "elapsed_ms": round(elapsed_ms, 1),
            "used_preagg": used_preagg,
            "payload": payload,
        }
    except Exception as exc:
        results[idx] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--team-id", type=int, required=True)
    parser.add_argument("--host", type=str, default=None, help="Override $host (else picked from data)")
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--date-from", type=str, default="-7d")
    parser.add_argument("--date-to", type=str, default=None)
    parser.add_argument("--second-wave", action="store_true", help="Fire a second wave after cache is primed to verify hits")
    parser.add_argument("--skip-clear", action="store_true", help="Don't wipe prior jobs/preagg rows")
    args = parser.parse_args()

    team = Team.objects.get(pk=args.team_id)

    # Enroll the team in the lazy preagg path
    set_instance_setting("WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS", [team.pk])
    print(f"[stress] enabled lazy preagg for team {team.pk} ({team.name!r})")

    host = args.host or pick_top_host(team)
    if not host:
        sys.exit("[stress] could not find a $host with traffic for this team — pass --host explicitly")
    print(f"[stress] using host={host!r}, window={args.date_from} → {args.date_to or 'now'}")

    # Clear any prior precompute jobs for a clean baseline
    if not args.skip_clear:
        PreaggregationJob.objects.filter(team=team).delete()
        sync_execute(
            "ALTER TABLE sharded_web_overview_preaggregated DELETE WHERE team_id = %(team_id)s",
            {"team_id": team.pk},
            settings={"mutations_sync": 2},
        )
        print("[stress] cleared prior jobs + preagg rows")
    else:
        print("[stress] skip-clear: leaving prior jobs + preagg rows in place")

    # Fire N concurrent requests
    N = args.concurrency
    results: list = [None] * N
    threads: list[threading.Thread] = []
    barrier = threading.Barrier(N)

    def runner_fn(i: int):
        barrier.wait()  # release all threads ~simultaneously
        fire_one(team, host, args.date_from, args.date_to, results, i)

    start = time.monotonic()
    for i in range(N):
        t = threading.Thread(target=runner_fn, args=(i,), daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join()
    wall = time.monotonic() - start

    # Summarize
    oks = [r for r in results if r and r.get("ok")]
    errs = [r for r in results if r and not r.get("ok")]
    print(f"\n[stress] {len(oks)}/{N} ok, {len(errs)} errors, wall={wall:.2f}s")
    if oks:
        elapsed_list = [r["elapsed_ms"] for r in oks]
        used_preagg = sum(1 for r in oks if r["used_preagg"])
        print(f"  per-call ms: min={min(elapsed_list):.0f} p50={sorted(elapsed_list)[N // 2]:.0f} max={max(elapsed_list):.0f}")
        print(f"  used_preagg=true on {used_preagg}/{len(oks)} responses")
    for e in errs[:3]:
        print(f"  ERR: {e['error']}")

    # Check 1: payload determinism across concurrent calls
    payloads = [json.dumps(r["payload"], sort_keys=True, default=str) for r in oks]
    distinct = set(payloads)
    if len(distinct) <= 1:
        print(f"\n  [✓] all {len(oks)} responses returned identical payloads")
    else:
        print(f"\n  [✗] payload divergence: {len(distinct)} distinct results across {len(oks)} calls")
        for i, p in enumerate(distinct):
            print(f"     variant {i}: {p[:200]}")

    # Check 2: Postgres job rows
    pg_rows = PreaggregationJob.objects.filter(team=team).values("query_hash", "status", "time_range_start", "time_range_end").order_by("time_range_start")
    print(f"\n  PG analytics_platform_preaggregationjob: {pg_rows.count()} row(s)")
    by_range: dict = {}
    for r in pg_rows:
        key = (r["query_hash"], r["time_range_start"], r["time_range_end"])
        by_range.setdefault(key, []).append(r["status"])
    over_one = {k: v for k, v in by_range.items() if len(v) > 1}
    if not over_one:
        print(f"  [✓] one job per (query_hash, range) tuple — no duplicate INSERTs raced through")
    else:
        print(f"  [✗] {len(over_one)} (query_hash, range) tuples have >1 job:")
        for k, statuses in list(over_one.items())[:5]:
            print(f"     {k}: {statuses}")

    # Check 3: ClickHouse preagg rows (FINAL to collapse any RMT duplicates)
    ch_rows = sync_execute(
        """
        SELECT
            time_window_start,
            job_id,
            count() AS dup_count
        FROM web_overview_preaggregated FINAL
        WHERE team_id = %(team_id)s
        GROUP BY time_window_start, job_id
        ORDER BY time_window_start
        """,
        {"team_id": team.pk},
    )
    distinct_jobs = {row[1] for row in ch_rows}
    dups = [row for row in ch_rows if row[2] > 1]
    print(f"\n  CH web_overview_preaggregated FINAL: {len(ch_rows)} (time_window_start, job_id) tuples")
    print(f"  distinct job_ids in CH: {len(distinct_jobs)}")
    if not dups:
        print(f"  [✓] no (time_window_start, job_id) duplicates after FINAL collapse")
    else:
        print(f"  [✗] {len(dups)} tuples have >1 row after FINAL:")
        for r in dups[:5]:
            print(f"     time_window_start={r[0]} job_id={r[1]} dup_count={r[2]}")

    # Inspect query_log for `web_overview_lazy_insert` and `web_overview_lazy_query` tags
    log_rows = sync_execute(
        """
        SELECT
            JSONExtractString(log_comment, 'query_type') AS query_type,
            count() AS c,
            min(query_start_time) AS first_seen,
            max(query_start_time) AS last_seen
        FROM clusterAllReplicas(posthog, system, query_log)
        WHERE query_start_time > now() - INTERVAL 5 MINUTE
          AND JSONExtractString(log_comment, 'team_id') = %(team_id)s
          AND type = 'QueryFinish'
          AND JSONExtractString(log_comment, 'query_type') LIKE 'web_overview_lazy%%'
        GROUP BY query_type
        """,
        {"team_id": str(team.pk)},
    )
    print("\n  ClickHouse query_log (last 5 min):")
    for row in log_rows:
        print(f"    {row[0]}: count={row[1]} first={row[2]} last={row[3]}")
    if not log_rows:
        print("    (none — lazy path may not have fired; check team enrollment and gate)")

    # Optional second wave: cache should be primed; expect zero new INSERTs
    if args.second_wave:
        print("\n[stress] === SECOND WAVE (cache should be primed) ===")
        pre_wave_inserts = next(
            (r[1] for r in log_rows if r[0] == "web_overview_lazy_insert"), 0
        )
        pre_wave_jobs = PreaggregationJob.objects.filter(team=team).count()

        results2: list = [None] * N
        threads2: list[threading.Thread] = []
        barrier2 = threading.Barrier(N)

        def runner_fn2(i: int):
            barrier2.wait()
            tag_queries(product=Product.WEB_ANALYTICS, feature=Feature.QUERY, team_id=team.pk)
            fire_one(team, host, args.date_from, args.date_to, results2, i)

        start2 = time.monotonic()
        for i in range(N):
            t = threading.Thread(target=runner_fn2, args=(i,), daemon=True)
            t.start()
            threads2.append(t)
        for t in threads2:
            t.join()
        wall2 = time.monotonic() - start2

        oks2 = [r for r in results2 if r and r.get("ok")]
        elapsed2 = [r["elapsed_ms"] for r in oks2]
        print(f"  {len(oks2)}/{N} ok, wall={wall2:.2f}s, per-call ms: min={min(elapsed2):.0f} p50={sorted(elapsed2)[N // 2]:.0f} max={max(elapsed2):.0f}")

        post_wave_jobs = PreaggregationJob.objects.filter(team=team).count()
        delta_jobs = post_wave_jobs - pre_wave_jobs
        if delta_jobs == 0:
            print(f"  [✓] no new PG jobs created during second wave (cache hit)")
        else:
            print(f"  [✗] {delta_jobs} new PG jobs created during second wave — cache miss?")


if __name__ == "__main__":
    with tags_context(product=Product.WEB_ANALYTICS, feature=Feature.QUERY):
        main()
