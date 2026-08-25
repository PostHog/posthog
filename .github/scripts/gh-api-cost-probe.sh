#!/usr/bin/env bash
# Measures how many GitHub REST requests a CI step costs, by reading the token's
# own /rate_limit bucket before and after it.
#
# GitHub documents /rate_limit as not counting against the limit it reports, so
# sampling is free and can bracket every step under test. The bucket belongs to
# whichever token authenticates the sample, so PROBE_TOKEN must be the same token
# the step under test uses, or the reading describes a different bucket.
#
# Throwaway: this exists for the rate-limit investigation and is deleted with it.

set -euo pipefail

STATE_DIR="${RUNNER_TEMP:-/tmp}/gh-api-cost-probe"
POSTHOG_HOST='https://us.i.posthog.com'
EVENT_NAME='github_api_cost_probe'
SUMMARY_HEADER_SENTINEL="$STATE_DIR/.summary-header-written"

die() {
    echo "::error::$*"
    exit 1
}

require_token() {
    # A silent fall back to github.token would still produce a plausible-looking
    # delta, measured against the wrong bucket. Fail instead.
    [[ -n "${PROBE_TOKEN:-}" ]] || die 'PROBE_TOKEN is empty; the App token mint failed and the measurement would read the wrong bucket'
}

# sample <name> — records the core bucket's counters under <name>.
sample() {
    local name="$1"
    require_token
    mkdir -p "$STATE_DIR"

    local body
    body=$(curl -fsS --connect-timeout 10 \
        -H "Authorization: Bearer ${PROBE_TOKEN}" \
        -H 'Accept: application/vnd.github+json' \
        -H 'X-GitHub-Api-Version: 2022-11-28' \
        https://api.github.com/rate_limit)

    local used limit reset
    used=$(jq -er '.resources.core.used' <<<"$body")
    limit=$(jq -er '.resources.core.limit' <<<"$body")
    reset=$(jq -er '.resources.core.reset' <<<"$body")

    printf '%s %s %s\n' "$used" "$reset" "$limit" >"$STATE_DIR/$name"
    echo "sample[$name] used=$used limit=$limit reset=$reset"

    if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
        {
            echo "${name}_used=$used"
            echo "${name}_reset=$reset"
        } >>"$GITHUB_OUTPUT"
    fi
}

# calibrate [n] — spends n requests on a known-cost call and asserts the bucket
# moved by exactly n.
#
# /rate_limit cannot be assumed to describe the token that asks. Measured against
# a GitHub CLI user-to-server token, it reported used=0 and reset=now+3600 on
# every call while `X-RateLimit-Used` on real endpoints read 1132 and climbed by
# one per request: for that token type the endpoint tracks a different, empty
# bucket. Installation tokens are the case this harness measures and they are
# believed to report correctly, but "believed" is not a measurement. Every job
# proves its instrument before trusting a single number out of it.
calibrate() {
    local n="${1:-3}"
    require_token
    [[ -n "${GITHUB_REPOSITORY:-}" ]] || die 'GITHUB_REPOSITORY is required to calibrate'

    sample cal_before >/dev/null

    local header_used='' i
    for ((i = 0; i < n; i++)); do
        header_used=$(curl -fsS -o /dev/null -D - \
            -H "Authorization: Bearer ${PROBE_TOKEN}" \
            -H 'Accept: application/vnd.github+json' \
            -H 'X-GitHub-Api-Version: 2022-11-28' \
            "https://api.github.com/repos/${GITHUB_REPOSITORY}" |
            tr -d '\r' | awk 'tolower($1) == "x-ratelimit-used:" {print $2}')
    done

    sample cal_after >/dev/null

    local before after reset_before reset_after _limit
    read -r before reset_before _limit <"$STATE_DIR/cal_before"
    read -r after reset_after _limit <"$STATE_DIR/cal_after"
    local observed=$((after - before))

    record instrument_calibration "$before" "$after" "$reset_before" "$reset_after" \
        "expected $n; X-RateLimit-Used header last read $header_used"

    if ((observed != n)); then
        die "instrument calibration failed: $n known requests moved /rate_limit by $observed. Every delta in this job is untrustworthy."
    fi
    echo "calibration ok: $n requests moved the bucket by $observed"
}

summary_header() {
    [[ -n "${GITHUB_STEP_SUMMARY:-}" ]] || return 0
    [[ -f "$SUMMARY_HEADER_SENTINEL" ]] && return 0
    mkdir -p "$STATE_DIR"
    {
        echo "### API cost: ${GITHUB_JOB:-unknown job}"
        echo
        echo '| Measurement | Bucket | used before | used after | Requests consumed | Note |'
        echo '| --- | --- | ---: | ---: | ---: | --- |'
    } >>"$GITHUB_STEP_SUMMARY"
    touch "$SUMMARY_HEADER_SENTINEL"
}

# record <measurement> <used_before> <used_after> <reset_before> <reset_after> [note]
# The raw-number form, so a job can report a delta spanning two other jobs.
record() {
    local measurement="$1" before="$2" after="$3" reset_before="$4" reset_after="$5" note="${6:-}"
    local bucket="${PROBE_BUCKET:-unknown}"

    # A job that failed before it sampled hands its reader an empty output, and
    # bash would read that as zero and publish a confident wrong number.
    local field
    for field in "$before" "$after" "$reset_before" "$reset_after"; do
        [[ "$field" =~ ^[0-9]+$ ]] || die "[$measurement] missing or non-numeric sample; an upstream job did not report one"
    done

    local delta=$((after - before))
    local rolled=false

    # The bucket resets hourly, and a reset between the two samples zeroes `used`,
    # which makes the subtraction meaningless. `reset` alone cannot detect that:
    # on a bucket sitting at used=0 GitHub reports reset as now+3600, so the field
    # advances every second without any window having rolled. A drop in `used` is
    # the signal that survives. Both reset stamps are published so the call can be
    # audited rather than taken on trust.
    if ((after < before)); then
        rolled=true
        note="${note:+$note; }used decreased, so the reset window rolled between samples and the delta is meaningless"
        echo "::warning::[$measurement] rate-limit window rolled between samples"
    fi

    echo "result[$measurement] delta=$delta (before=$before after=$after bucket=$bucket reset_before=$reset_before reset_after=$reset_after)"

    summary_header
    if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
        local shown="$delta"
        [[ "$rolled" == true ]] && shown='n/a'
        echo "| $measurement | $bucket | $before | $after | $shown | ${note:--} |" >>"$GITHUB_STEP_SUMMARY"
    fi

    capture "$measurement" "$before" "$after" "$delta" "$rolled" "$note" "$reset_before" "$reset_after"
}

# delta <measurement> <before_name> <after_name> [note] — the two-samples-in-one-job form.
delta() {
    local measurement="$1" before_name="$2" after_name="$3" note="${4:-}"
    local before_used before_reset after_used after_reset _limit
    read -r before_used before_reset _limit <"$STATE_DIR/$before_name"
    read -r after_used after_reset _limit <"$STATE_DIR/$after_name"
    record "$measurement" "$before_used" "$after_used" "$before_reset" "$after_reset" "$note"
}

# note <text> — free-form line under the job's table, for evidence that isn't a delta.
note() {
    [[ -n "${GITHUB_STEP_SUMMARY:-}" ]] || return 0
    summary_header
    printf '\n%s\n' "$1" >>"$GITHUB_STEP_SUMMARY"
}

capture() {
    local measurement="$1" before="$2" after="$3" delta_value="$4" rolled="$5" note_text="$6"
    local reset_before="$7" reset_after="$8"
    [[ -n "${POSTHOG_DEVEX_PROJECT_API_TOKEN:-}" ]] || {
        echo 'POSTHOG_DEVEX_PROJECT_API_TOKEN not set; skipping capture'
        return 0
    }

    local payload
    payload=$(jq -n \
        --arg api_key "$POSTHOG_DEVEX_PROJECT_API_TOKEN" \
        --arg event "$EVENT_NAME" \
        --arg distinct_id "${GITHUB_REPOSITORY:-unknown}" \
        --arg measurement "$measurement" \
        --arg bucket "${PROBE_BUCKET:-unknown}" \
        --arg note "$note_text" \
        --arg job "${GITHUB_JOB:-unknown}" \
        --arg runner "${RUNNER_LABEL:-unknown}" \
        --arg repo "${GITHUB_REPOSITORY:-unknown}" \
        --arg run_id "${GITHUB_RUN_ID:-}" \
        --arg run_attempt "${GITHUB_RUN_ATTEMPT:-}" \
        --argjson used_before "$before" \
        --argjson used_after "$after" \
        --argjson requests "$delta_value" \
        --argjson window_rolled "$rolled" \
        --argjson reset_before "$reset_before" \
        --argjson reset_after "$reset_after" \
        '{api_key: $api_key, event: $event, distinct_id: $distinct_id, properties: {
            measurement: $measurement, bucket: $bucket, used_before: $used_before,
            used_after: $used_after, requests: $requests, window_rolled: $window_rolled,
            reset_before: $reset_before, reset_after: $reset_after,
            note: $note, job: $job, runner: $runner, repo: $repo,
            workflow_run_id: $run_id, workflow_run_attempt: $run_attempt
        }}')

    # Telemetry, not idempotent — a retry would double-count the measurement.
    curl -fsS --connect-timeout 10 -o /dev/null \
        -X POST -H 'Content-Type: application/json' \
        -d "$payload" "$POSTHOG_HOST/capture/" ||
        echo "::warning::failed to capture $measurement to PostHog"
}

command="${1:-}"
shift || true
case "$command" in
sample | record | delta | note | calibrate) "$command" "$@" ;;
*) die "unknown command '${command}' (expected: sample | record | delta | note | calibrate)" ;;
esac
