#!/usr/bin/env bash
# Runs a command under a wall-clock bound set below the job's timeout-minutes.
#
# If the bound is hit, captures a native stack dump of every live pytest
# process before killing the command. py-spy attaches from outside the process
# (via ptrace), so it works even when the hang is wedged inside a native call
# holding the GIL — the case where in-process watchdogs (pytest-timeout's
# signal and thread methods) cannot run at all.
#
# Failing the *step* (instead of letting the job hit timeout-minutes) matters:
# a job-level timeout cancels the job and GitHub discards the in-progress
# step's log, destroying the evidence along with it.
set -uo pipefail

BOUND_SECONDS="${AUTOPSY_BOUND_SECONDS:-1500}"

maybe_sudo() {
    if command -v sudo >/dev/null 2>&1; then
        sudo "$@"
    else
        "$@"
    fi
}

find_py_spy() {
    command -v py-spy && return 0
    uv tool install py-spy >/dev/null 2>&1 || pip install --quiet py-spy >/dev/null 2>&1 || true
    if [ -x "$HOME/.local/bin/py-spy" ]; then
        echo "$HOME/.local/bin/py-spy"
        return 0
    fi
    command -v py-spy
}

autopsy() {
    echo "::error::Command still running after ${BOUND_SECONDS}s — capturing stack dumps before killing it"
    echo "===== process tree ====="
    # --ppid 2 -p 2 --deselect: everything except kernel threads
    ps -f --forest --ppid 2 -p 2 --deselect || ps -ef --forest || true

    local py_spy
    py_spy="$(find_py_spy || true)"
    if [ -z "$py_spy" ]; then
        echo "py-spy unavailable — skipping Python stack dumps"
        return
    fi

    local pids
    pids="$(pgrep -x pytest || true)"
    if [ -z "$pids" ]; then
        echo "No pytest processes found — the hang is outside pytest (see process tree above)"
        return
    fi

    dump_pg_activity

    local pid
    for pid in $pids; do
        echo "===== py-spy dump --native (pid ${pid}) ====="
        ps -o pid,ppid,etime,wchan:32,cmd -p "$pid" || true
        # --native pauses the process to walk C frames; fall back to
        # --nonblocking (less exact) and then to pure-Python frames.
        maybe_sudo "$py_spy" dump --native --pid "$pid" ||
            maybe_sudo "$py_spy" dump --native --nonblocking --pid "$pid" ||
            maybe_sudo "$py_spy" dump --pid "$pid" || true
        echo
    done
}

dump_pg_activity() {
    [ -z "${DATABASE_URL:-}" ] && return 0
    echo "===== pg_stat_activity (lock holders) ====="
    # The hang signature is a teardown TRUNCATE blocked on another session's
    # lock; pg_blocking_pids names the holder. Tests run on test_posthog.
    python3 - <<'PYEOF' || true
import os
import psycopg

with psycopg.connect(os.environ["DATABASE_URL"], dbname="test_posthog", connect_timeout=5) as conn:
    rows = conn.execute(
        """
        SELECT pid, pg_blocking_pids(pid) AS blocked_by, state,
               wait_event_type, wait_event, now() - xact_start AS xact_age,
               application_name, left(query, 240) AS query
        FROM pg_stat_activity
        WHERE datname = current_database() AND pid <> pg_backend_pid()
        ORDER BY xact_start NULLS LAST
        """
    ).fetchall()
    for row in rows:
        print(row)
PYEOF
}

# setsid: own process group, so the watchdog can kill the full tree (turbo
# spawns pnpm -> pytest children; killing only the leader would leave orphans
# holding the step's stdout open).
setsid "$@" &
cmd_pid=$!

(
    sleep "$BOUND_SECONDS"
    autopsy
    echo "Killing process group ${cmd_pid}"
    kill -9 -- "-${cmd_pid}" 2>/dev/null || true
) &
watchdog_pid=$!

wait "$cmd_pid"
status=$?
# Kill the watchdog's sleep child too — an orphaned sleep would hold the
# step's stdout pipe open long after the tests finish.
pkill -P "$watchdog_pid" 2>/dev/null || true
kill "$watchdog_pid" 2>/dev/null || true
exit "$status"
