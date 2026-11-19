#!/usr/bin/env bash
set -uo pipefail

INVALID=2

export HOME="${HOME:-/root}"
export PATH="$HOME/.cargo/bin:$PATH"
repo=$(cd "$(dirname "$0")/../../../.." && pwd)
prefix="s3://${SCENARIO_EVIDENCE_BUCKET}/runs/${SCENARIO_RUN_ID}"
root=$(realpath -m -- "${SCENARIO_HOST_ROOT:-/opt/scenario}") || exit
input=$root/input
evidence=$root/evidence
process_logs=${SCENARIO_PROCESS_LOGS:-$repo/.posthog/.generated/logs}
export XDG_CACHE_HOME=$root/cache
export SCENARIO_RUN_MANIFEST="$input/manifest.json"
code=$INVALID
card=

now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

mark() {
    printf '%s\n' "$2" | aws s3 cp - "$prefix/host/$1"
}

checksums() (
    cd "$evidence" || exit 1
    find . -type f ! -name SHA256SUMS -print0 | sort -z >"$root/evidence.list" || exit 1
    while IFS= read -r -d '' file; do
        sum=$(sha256sum <"$file") || exit 1
        printf '%s  %s\n' "${sum%% *}" "$file"
    done <"$root/evidence.list"
)

upload_evidence() {
    local run log
    mkdir -p "$evidence/run"
    for log in "$XDG_CACHE_HOME"/posthog-scenarios/*.log; do
        if [ -f "$log" ]; then
            cp "$log" "$evidence/" || return 1
        fi
    done
    for log in "$process_logs"/*.log; do
        if [ -f "$log" ]; then
            mkdir -p "$evidence/processes" && tail -n 2000 <"$log" >"$evidence/processes/${log##*/}" || return 1
        fi
    done
    for run in "$XDG_CACHE_HOME"/posthog-scenarios/*-*-*-*-*/; do
        if [ -d "$run" ]; then
            cp -r "$run" "$evidence/run/" || return 1
        fi
    done
    checksums >"$root/SHA256SUMS" &&
        mv "$root/SHA256SUMS" "$evidence/SHA256SUMS" &&
        aws s3 cp --recursive --only-show-errors "$evidence/" "$prefix/evidence/"
}

finish() {
    trap - TERM INT
    local uploaded=true
    upload_evidence || uploaded=false
    mark 'done' "{\"exitCode\":$code,\"uploaded\":$uploaded,\"at\":\"$(now)\"}"
    if [ -n "${live:-}" ]; then
        wait "$live" 2>/dev/null || true
    fi
}

stop() {
    if [ -n "$card" ]; then
        kill -TERM "$card" 2>/dev/null
    fi
}

mkdir -p "$evidence"
trap stop TERM INT
trap finish EXIT
mark started "{\"at\":\"$(now)\"}" || exit
card_id=$(jq -r '.card // empty' "$SCENARIO_RUN_MANIFEST") && [[ $card_id =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]] || exit
SCENARIO_POOLER_URLS=$(cat "$root/pooler/urls") || exit
export SCENARIO_POOLER_URLS
(cd "$repo/nodejs" && exec node --import tsx tests/scenarios/main.ts run "$card_id" --profile "$input/runner-profile.yaml") >"$evidence/card.log" 2>&1 &
card=$!
bash "$repo/nodejs/tests/scenarios/cloud/host-live-copy.sh" "$XDG_CACHE_HOME/posthog-scenarios/$SCENARIO_RUN_ID/live.jsonl" "$prefix/live.jsonl" "$card" "$$" &
live=$!
while kill -0 "$card" 2>/dev/null; do
    wait "$card"
done
wait "$card"
code=$?
kill -TERM "$live" 2>/dev/null || true
