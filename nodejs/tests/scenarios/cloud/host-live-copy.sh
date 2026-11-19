#!/usr/bin/env bash
set -uo pipefail

if [ $# -ne 4 ]; then
    echo "Usage: $0 <runner state dir> <s3 target> <runner pid> <wrapper pid>" >&2
    exit 0
fi

state=$1
target=$2
runner=$3
wrapper=$4
interval=${SCENARIO_LIVE_COPY_SECONDS:-5}
final_limit=${SCENARIO_LIVE_COPY_FINAL_SECONDS:-20}
copied=0
copying=
sleeping=
several=false

say() { printf 'host-live-copy: %s\n' "$1" >&2; }

started_at() {
    local boot ticks
    boot=$(awk '$1 == "btime" { print $2 }' /proc/stat) &&
        ticks=$(awk '{ print $22 }' "/proc/$1/stat") &&
        [ -n "$boot" ] && [ -n "$ticks" ] &&
        echo $((boot + ticks / $(getconf CLK_TCK) - 1))
}

newest_log() {
    local found
    found=$(find "$state" -mindepth 2 -maxdepth 2 -name live.jsonl -newermt "@$since" -printf '%T@ %p\n' 2>/dev/null | sort -n)
    [ -n "$found" ] || return 1
    if ! $several && [ "$(wc -l <<<"$found")" -gt 1 ]; then
        several=true
        say "found more than one live log since the run started, copying the newest"
    fi
    tail -n 1 <<<"$found" | cut -d ' ' -f 2-
}

whole_lines_of() {
    local partial
    cp "$1" "$snapshot" || return 1
    if [ -n "$(tail -c 1 "$snapshot")" ]; then
        partial=$(tail -n 1 "$snapshot" | wc -c)
        truncate -s "-$partial" "$snapshot" || return 1
    fi
    stat -c %s "$snapshot"
}

copy() {
    local log size status
    log=$(newest_log) || return 0
    size=$(whole_lines_of "$log") || {
        say "could not read the live log"
        return 0
    }
    [ "$size" -gt "$copied" ] || return 0
    timeout "$1" aws s3 cp --only-show-errors - "$target" <"$snapshot" >/dev/null 2>&1 &
    copying=$!
    wait "$copying"
    status=$?
    copying=
    if [ "$status" = 0 ]; then
        copied=$size
    else
        say "copy failed (exit $status)"
    fi
}

finish() {
    trap '' TERM
    for child in $copying $sleeping; do
        kill -TERM "$child" 2>/dev/null
    done
    copying=
    copy "$final_limit"
    rm -f "$snapshot"
    exit 0
}

if [ -z "${SCENARIO_EVIDENCE_BUCKET:-}" ] || [ "${SCENARIO_LIVE_COPY:-on}" = off ]; then
    exit 0
fi
since=$(started_at "$wrapper") || exit 0
snapshot=$(mktemp) || exit 0
trap finish TERM
while kill -0 "$wrapper" 2>/dev/null; do
    kill -0 "$runner" 2>/dev/null || finish
    copy "$interval"
    sleep "$interval" </dev/null >/dev/null 2>&1 &
    sleeping=$!
    wait "$sleeping"
    sleeping=
done
rm -f "$snapshot"
