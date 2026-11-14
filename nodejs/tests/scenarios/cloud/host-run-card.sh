#!/usr/bin/env bash
set -uo pipefail

CARD=cyclotron-failover-under-load
INVALID=2

export HOME="${HOME:-/root}"
repo=$(cd "$(dirname "$0")/../../../.." && pwd)
prefix="s3://${SCENARIO_EVIDENCE_BUCKET}/runs/${SCENARIO_RUN_ID}"
root=${SCENARIO_HOST_ROOT:-/opt/scenario}
input=$root/input
evidence=$root/evidence
export XDG_CACHE_HOME=$root/cache
export SCENARIO_RUN_MANIFEST="$input/manifest.json"
code=$INVALID
card=

now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

mark() {
    printf '%s\n' "$2" | aws s3 cp - "$prefix/host/$1"
}

upload_evidence() {
    local run
    mkdir -p "$evidence/run"
    for run in "$XDG_CACHE_HOME"/posthog-scenarios/*-*-*-*-*/; do
        if [ -d "$run" ]; then
            cp -r "$run" "$evidence/run/" || return 1
        fi
    done
    (cd "$evidence" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 -r sha256sum) >"$root/SHA256SUMS" &&
        mv "$root/SHA256SUMS" "$evidence/SHA256SUMS" &&
        aws s3 cp --recursive --only-show-errors "$evidence/" "$prefix/evidence/"
}

finish() {
    trap - TERM INT
    local uploaded=true
    upload_evidence || uploaded=false
    mark 'done' "{\"exitCode\":$code,\"uploaded\":$uploaded,\"at\":\"$(now)\"}"
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
(cd "$repo/nodejs" && exec node --import tsx tests/scenarios/main.ts run "$CARD" --profile "$input/runner-profile.yaml") >"$evidence/card.log" 2>&1 &
card=$!
while kill -0 "$card" 2>/dev/null; do
    wait "$card"
done
wait "$card"
code=$?
