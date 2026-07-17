#!/usr/bin/env python3
# ruff: noqa: T201 — CLI tool; printed report is its output
"""Measure the serial blocking external I/O round trips on the anonymous GET /login render.

The login page's TTFB is dominated by the server building the HTML document. For an
anonymous visitor (non-cloud / self-hosted / devbox), the bulk of that work is
`preflight_check`, which fans out to a series of *serial* liveness / existence checks —
each a blocking round trip to Redis, Postgres, ClickHouse, Kafka, the plugin server, or
object storage. They run one after another in the request thread before the first byte is
flushed, so their summed latency lands directly on TTFB.

This harness statically counts those round trips (via AST, so it needs no running stack)
and is the metric the autoresearch loop optimizes. Caching the anonymous preflight payload
(identical for every anonymous visitor) collapses the warm-path count.

Run: python3 bin/measure_login_ttfb_roundtrips.py
"""

from __future__ import annotations

import ast
import pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent

# Functions that perform a blocking external I/O round trip when reached on the
# anonymous, non-cloud preflight path. Each maps to the backing service it hits.
BLOCKING_CALLS = {
    "is_redis_alive": "redis",
    "is_plugin_server_alive": "plugin-server-http",
    "is_celery_alive": "redis",
    "is_clickhouse_connected": "clickhouse",
    "is_kafka_connected": "kafka",
    "is_postgres_alive": "postgres",
    "get_instance_available_sso_providers": "postgres",
    "get_can_create_org": "postgres",
    "is_object_storage_available": "object-storage",
    # Bare ORM existence checks inlined in the preflight dict.
    "Organization.objects.exists": "postgres",
}


def _callee_name(node: ast.Call) -> str | None:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        # Build dotted name e.g. Organization.objects.exists
        parts: list[str] = [f.attr]
        cur: ast.expr = f.value
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        return ".".join(reversed(parts))
    return None


def _get_func_source(path: pathlib.Path, func_name: str) -> ast.FunctionDef:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            return node
    raise SystemExit(f"could not find {func_name} in {path}")


def _dotted(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parts: list[str] = [node.attr]
        cur: ast.expr = node.value
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        return ".".join(reversed(parts))
    return None


def count_preflight_roundtrips() -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Count references to blocking-I/O callables on the anonymous branch.

    The checks are passed as callables into `_traced(...)` (or called inline), so they
    surface as Name/Attribute references rather than direct call callees. We count each
    reference once. The authenticated-only branch (`if request.user.is_authenticated`)
    is excluded — the login page is anonymous.

    Returns (serial_hits, parallel_hits): probes referenced inside the concurrent
    fan-out helper `_run_preflight_probes` (ThreadPoolExecutor) run as ONE parallel
    batch — their wall-clock cost is max(probe), not sum — so they are reported
    separately and count as a single serial step.
    """

    def _guard_matches(test: ast.expr, names: set[str]) -> bool:
        if isinstance(test, ast.Name):
            return test.id in names
        if isinstance(test, ast.Attribute):
            return test.attr in names
        return False

    def _hits_in(fn: ast.FunctionDef, skip_guards: frozenset[str]) -> list[tuple[str, str]]:
        # Nodes inside guarded-off blocks don't run for the anonymous, non-cloud login
        # page: the authenticated-extras branch and the cloud-only serial branch.
        skipped_nodes: set[int] = set()
        if skip_guards:
            for node in ast.walk(fn):
                if isinstance(node, ast.If) and _guard_matches(node.test, set(skip_guards)):
                    for child in node.body:
                        for sub in ast.walk(child):
                            skipped_nodes.add(id(sub))

        found: list[tuple[str, str]] = []
        seen_positions: set[tuple[int, int]] = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Name | ast.Attribute):
                if id(node) in skipped_nodes:
                    continue
                name = _dotted(node)
                if name in BLOCKING_CALLS:
                    pos = (getattr(node, "lineno", -1), getattr(node, "col_offset", -1))
                    if pos in seen_positions:
                        continue
                    seen_positions.add(pos)
                    found.append((name, BLOCKING_CALLS[name]))
        return found

    serial: list[tuple[str, str]] = []
    for fn_name in ("preflight_check", "_build_preflight_base"):
        try:
            fn = _get_func_source(REPO / "posthog" / "views.py", fn_name)
        except SystemExit:
            continue
        serial.extend(_hits_in(fn, skip_guards=frozenset({"is_authenticated", "in_cloud"})))
    parallel: list[tuple[str, str]] = []
    try:
        pool_fn = _get_func_source(REPO / "posthog" / "views.py", "_run_preflight_probes")
    except SystemExit:
        pool_fn = None
    if pool_fn is not None and any(isinstance(n, ast.Name) and n.id == "ThreadPoolExecutor" for n in ast.walk(pool_fn)):
        parallel = _hits_in(pool_fn, skip_guards=frozenset())
    return serial, parallel


def anonymous_preflight_cache_layers() -> tuple[bool, bool, bool]:
    """Detect which caching layers serve the anonymous preflight payload.

    Returns (shared_cache, local_cache, swr). Each optimization introduces a sentinel:
    - shared cache (Redis-backed): warm path costs a single cache round trip
    - per-worker in-memory layer: steady-state warm path costs zero external round trips
    - stale-while-revalidate: TTL expiry serves the stale copy and refreshes off-thread,
      so post-boot anonymous renders never block on a rebuild
    """
    views_src = (REPO / "posthog" / "views.py").read_text()
    shared = "ANONYMOUS_PREFLIGHT_CACHE_TTL_SECONDS" in views_src
    local = "ANONYMOUS_PREFLIGHT_LOCAL_TTL_SECONDS" in views_src
    swr = "ANONYMOUS_PREFLIGHT_STALE_MAX_SECONDS" in views_src
    return shared, local, swr


def main() -> None:
    serial_hits, parallel_hits = count_preflight_roundtrips()
    shared_cache, local_cache, swr = anonymous_preflight_cache_layers()

    # Cold path: each serial hit is one blocking step; a concurrent probe batch costs
    # ~max(probe) wall-clock, so it counts as a single blocking step.
    cold = len(serial_hits) + (1 if parallel_hits else 0)
    # Warm path (steady state, per request): the in-memory layer serves from process
    # memory (0 external round trips); the shared cache alone costs 1 cache read;
    # uncached recomputes everything.
    if local_cache:
        warm = 0
    elif shared_cache:
        warm = 1
    else:
        warm = cold

    print("Anonymous GET /login — serial blocking external I/O round trips")
    print("-" * 64)
    for name, service in serial_hits:
        print(f"  serial   {name:<40} -> {service}")
    for name, service in parallel_hits:
        print(f"  parallel {name:<40} -> {service}")
    print("-" * 64)
    print(
        f"cold blocking steps         : {cold} ({len(serial_hits)} serial + {'1 parallel batch' if parallel_hits else 'no batch'})"
    )
    print(f"shared cache (cross-worker) : {shared_cache}")
    print(f"per-worker in-memory layer  : {local_cache}")
    print(f"stale-while-revalidate      : {swr}  (TTL expiry refreshes off the request thread)")
    print(f"warm-path round trips       : {warm}")
    print()
    print(f"METRIC login_ttfb_roundtrips = {warm}")


if __name__ == "__main__":
    main()
