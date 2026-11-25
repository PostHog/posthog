#!/usr/bin/env bash
set -uo pipefail

if [ $# -ne 4 ]; then
    echo "Usage: $0 <live log> <s3 target> <runner pid> <wrapper pid>" >&2
    exit 0
fi

log=$1
target=$2
runner=$3
wrapper=$4
interval=${SCENARIO_LIVE_COPY_SECONDS:-5}
limit=${SCENARIO_LIVE_COPY_LIMIT_SECONDS:-10}
copied=0

say() { printf 'host-live-copy: %s\n' "$1" >&2; }

whole_lines_of_log() {
    local partial
    cp "$log" "$snapshot" || return 1
    if [ -n "$(tail -c 1 "$snapshot")" ]; then
        partial=$(tail -n 1 "$snapshot" | wc -c)
        truncate -s "-$partial" "$snapshot" || return 1
    fi
    stat -c %s "$snapshot"
}

follow() {
    local stopped=
    while kill -0 "$1" 2>/dev/null; do
        if [ -z "$stopped" ] && ! kill -0 "$wrapper" 2>/dev/null; then
            kill -TERM "$1" 2>/dev/null
            stopped=1
        fi
        sleep 0.2 </dev/null >/dev/null 2>&1 &
        wait $!
    done
    wait "$1"
}

copy() {
    local size status
    size=$(stat -c %s "$log" 2>/dev/null) && [ "$size" -gt "$copied" ] || return 0
    size=$(whole_lines_of_log) || {
        say "could not read the live log"
        return 0
    }
    [ "$size" -gt "$copied" ] || return 0
    timeout --foreground -k 2 "$limit" aws s3 cp --only-show-errors - "$target" <"$snapshot" >/dev/null 2>&1 &
    follow $!
    status=$?
    if [ "$status" = 0 ]; then
        copied=$size
    else
        say "copy failed (exit $status)"
    fi
}

finish() {
    trap '' TERM
    for child in $(jobs -p); do
        kill -TERM "$child" 2>/dev/null
    done
    wait
    while kill -0 "$runner" 2>/dev/null && kill -0 "$wrapper" 2>/dev/null; do
        sleep 0.2
    done
    if kill -0 "$wrapper" 2>/dev/null; then
        copy
    fi
    rm -f "$snapshot"
    exit 0
}

if [ -z "${SCENARIO_EVIDENCE_BUCKET:-}" ] || [ "${SCENARIO_LIVE_COPY:-on}" = off ]; then
    exit 0
fi
snapshot=$(mktemp) || exit 0
trap finish TERM
while kill -0 "$wrapper" 2>/dev/null; do
    kill -0 "$runner" 2>/dev/null || finish
    copy
    sleep "$interval" </dev/null >/dev/null 2>&1 &
    follow $!
done
rm -f "$snapshot"
