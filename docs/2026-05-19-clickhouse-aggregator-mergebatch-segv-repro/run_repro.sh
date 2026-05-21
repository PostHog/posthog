#!/usr/bin/env bash
#
# Self-contained reproduction of the ClickHouse 26.3.10.60 SIGSEGV in
# Aggregator::mergeBatch (two-level, String-keyed merge path).
#
# Spins up a *fresh* standalone clickhouse-server:26.3.10.60 container, runs the
# repro SQL against it, and confirms a new row in system.crash_log. No PostHog
# dev stack required.
#
# See README.md for the full diagnosis and what makes the bug trigger.
#
# Usage:
#   ./run_repro.sh [a|b|both]   # which repro to run (default: both)
#   ./run_repro.sh b --keep     # leave the container running afterwards
#   ./run_repro.sh --no-start b # reuse an already-running container
#
# Requires: docker, and an aarch64 host (Apple Silicon). The crash is
# architecture-specific to the aarch64 build.

set -uo pipefail

IMAGE="clickhouse/clickhouse-server:26.3.10.60"
NAME="ch-segv-repro"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

WHICH="both"
KEEP=0
START=1

usage() {
    sed -n '3,18p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

for arg in "$@"; do
    case "$arg" in
        a|b|both) WHICH="$arg" ;;
        --keep) KEEP=1 ;;
        --no-start) START=0 ;;
        -h|--help) usage 0 ;;
        *) echo "unknown argument: $arg" >&2; usage 1 ;;
    esac
done

BASELINE=0

ch() {
    # Run a query against the container, returning its output. Tolerant of a
    # dead server (the caller decides what a failure means).
    docker exec "$NAME" clickhouse-client "$@"
}

wait_ready() {
    # Wait for clickhouse-server to answer queries (initial boot or post-crash
    # auto-restart). Times out after ~60s.
    local i
    for i in $(seq 1 60); do
        if docker exec "$NAME" clickhouse-client -q "SELECT 1" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    echo "ERROR: clickhouse-server did not become ready within 60s" >&2
    docker logs --tail 40 "$NAME" >&2 || true
    exit 1
}

start_clickhouse() {
    echo "==> Starting fresh $IMAGE as '$NAME'"
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    # --add-host clickhouse:127.0.0.1 makes remote('clickhouse,clickhouse', ...)
    #   in the repro SQL resolve to this container's own :9000 (two pseudo-shards).
    # --restart=always brings the server back after the SIGSEGV kills the process,
    #   so system.crash_log (which persists on disk) stays queryable.
    docker run -d \
        --name "$NAME" \
        --restart=always \
        --add-host clickhouse:127.0.0.1 \
        "$IMAGE" >/dev/null
    wait_ready
    echo "==> clickhouse-server ready"
}

record_baseline() {
    BASELINE="$(ch -q "SELECT count() FROM system.crash_log" 2>/dev/null || echo 0)"
    BASELINE="${BASELINE:-0}"
}

# Print the newest crash_log row and assert the crash count grew. Returns 0 if a
# new crash was recorded, 1 otherwise.
check_crash() {
    local label="$1"
    echo "==> Waiting for clickhouse-server to restart after the crash"
    wait_ready
    local after
    after="$(ch -q "SELECT count() FROM system.crash_log" 2>/dev/null || echo 0)"
    after="${after:-0}"
    echo "==> Latest system.crash_log entry:"
    ch -q "SELECT event_time, signal, hex(fault_address) AS fault_address, trace_full[1] AS top_frame \
           FROM system.crash_log ORDER BY event_time DESC LIMIT 1 FORMAT Vertical" 2>/dev/null || true
    if [ "$after" -gt "$BASELINE" ]; then
        echo "==> PASS ($label): crash_log grew $BASELINE -> $after"
        BASELINE="$after"
        return 0
    fi
    echo "==> FAIL ($label): no new crash_log row (count still $after)" >&2
    return 1
}

run_repro_b() {
    echo
    echo "================ Repro B: anyIf(String) ================"
    # Single --multiquery session. The client reports a dropped connection when
    # the server dies mid-query; that is expected, so ignore its exit status.
    docker exec -i "$NAME" clickhouse-client --multiquery \
        < "$SCRIPT_DIR/repro_b_anyif_string.sql" || true
    check_crash "repro B"
}

run_repro_a() {
    echo
    echo "================ Repro A: argMinMerge(String) ================"
    # Setup (DDL + INSERT) and the crashing SELECT must run in SEPARATE client
    # invocations: a single session occasionally raises an unrelated
    # LOGICAL_ERROR that masks the crash. Split on the "CRASHING QUERY" banner.
    echo "==> Section 1: schema + INSERT"
    awk '/^-- ============= CRASHING/{exit} {print}' \
        "$SCRIPT_DIR/repro_a_argminmerge.sql" \
        | docker exec -i "$NAME" clickhouse-client --multiquery || true
    # The crashing SELECT races with an unrelated LOGICAL_ERROR on one of the
    # remote shards; retry up to 3 times to reliably land in the crash path.
    local attempt
    for attempt in 1 2 3; do
        echo "==> Section 2: crashing SELECT (attempt $attempt/3)"
        sed -n '/^-- ============= CRASHING/,$p' \
            "$SCRIPT_DIR/repro_a_argminmerge.sql" \
            | tail -n +2 \
            | docker exec -i "$NAME" clickhouse-client || true
        wait_ready
        local after
        after="$(ch -q "SELECT count() FROM system.crash_log" 2>/dev/null || echo 0)"
        if [ "${after:-0}" -gt "$BASELINE" ]; then
            break
        fi
    done
    check_crash "repro A"
}

teardown() {
    echo
    echo "==> Inspect crashes with:"
    echo "    docker exec $NAME clickhouse-client -q \\"
    echo "      \"SELECT event_time, hex(fault_address), trace_full[1] FROM system.crash_log ORDER BY event_time DESC FORMAT Vertical\""
    if [ "$KEEP" -eq 1 ]; then
        echo "==> Leaving container '$NAME' running (--keep). Remove with: docker rm -f $NAME"
    else
        echo "==> Removing container '$NAME' (pass --keep to retain it)"
        docker rm -f "$NAME" >/dev/null 2>&1 || true
    fi
}

main() {
    if [ "$START" -eq 1 ]; then
        start_clickhouse
    else
        echo "==> Reusing existing container '$NAME' (--no-start)"
        wait_ready
    fi
    record_baseline

    local rc=0
    case "$WHICH" in
        a) run_repro_a || rc=1 ;;
        b) run_repro_b || rc=1 ;;
        both) run_repro_b || rc=1; run_repro_a || rc=1 ;;
    esac

    teardown

    if [ "$rc" -eq 0 ]; then
        echo
        echo "==> Reproduced. Expected fault_address 010001000100, top frame ...mergeBatch."
    fi
    exit "$rc"
}

main
