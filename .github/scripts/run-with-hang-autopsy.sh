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
    ps -ef --forest || true

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
