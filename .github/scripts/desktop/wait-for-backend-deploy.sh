#!/usr/bin/env bash
# Blocks until every required backend SHA is contained in the latest successful
# deployment of each prod environment. Deployment records are written to this
# repo by PostHog/charts once ArgoCD reports the app synced and healthy.
# GitHub flips superseded deployments to "inactive", so the current state of
# the newest record is not the signal: scan newest-first for a deployment
# whose status history ever reached "success".
set -euo pipefail

REPOSITORY="${REPOSITORY:?}"
REQUIRED_SHAS="${REQUIRED_SHAS:-}"
POLL_SECONDS="${POLL_SECONDS:-90}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-4800}"
ENVIRONMENTS="${ENVIRONMENTS:-prod-us prod-eu}"

if [ -z "$REQUIRED_SHAS" ]; then
    echo "No required backend SHAs; nothing to wait for."
    exit 0
fi

IFS=' ' read -r -a required <<<"$REQUIRED_SHAS"
IFS=' ' read -r -a environments <<<"$ENVIRONMENTS"

latest_successful_sha() {
    local env="$1" page deployments id ref
    # 3 pages = 300 deployments, several days of history at the observed
    # ~15-minute deploy cadence; a healthy environment succeeds far sooner.
    for page in 1 2 3; do
        deployments=$(gh api "repos/$REPOSITORY/deployments?environment=$env&per_page=100&page=$page" 2>/dev/null || echo '[]')
        [ "$(jq 'length' <<<"$deployments")" -gt 0 ] || break
        while IFS=$'\t' read -r id ref; do
            if gh api "repos/$REPOSITORY/deployments/$id/statuses" 2>/dev/null |
                jq -e 'any(.[]; .state == "success")' >/dev/null; then
                echo "$ref"
                return 0
            fi
        done < <(jq -r '.[] | [(.id | tostring), .ref] | @tsv' <<<"$deployments")
    done
    echo ""
}

# required is deployed iff it is an ancestor of (or equal to) the deployed SHA.
is_deployed() {
    local status
    status=$(gh api "repos/$REPOSITORY/compare/$1...$2" 2>/dev/null | jq -r '.status // "error"')
    [ "$status" = "ahead" ] || [ "$status" = "identical" ]
}

start=$(date +%s)
while true; do
    satisfied=true
    for env in "${environments[@]}"; do
        deployed=$(latest_successful_sha "$env")
        if [ -z "$deployed" ]; then
            echo "[$env] no successful deployment found in recent history"
            satisfied=false
            continue
        fi
        for sha in "${required[@]}"; do
            if is_deployed "$sha" "$deployed"; then
                echo "[$env] $sha is live (latest successful deploy: $deployed)"
            else
                echo "[$env] $sha is not yet part of the latest successful deploy ($deployed)"
                satisfied=false
            fi
        done
    done

    if [ "$satisfied" = true ]; then
        echo "All required backend SHAs are deployed and healthy on: $ENVIRONMENTS"
        exit 0
    fi

    elapsed=$(($(date +%s) - start))
    if [ "$elapsed" -ge "$TIMEOUT_SECONDS" ]; then
        echo "::error::Timed out after ${elapsed}s waiting for backend SHAs ($REQUIRED_SHAS) on: $ENVIRONMENTS"
        echo "Once the backend deploy lands, re-run this run's failed jobs: the platform"
        echo "builds are kept and only this gate re-polls. If the dependency is safe to"
        echo "skip, apply the desktop-skip-backend-gate label to the coupled PR and re-run."
        exit 1
    fi
    echo "Not satisfied; next check in ${POLL_SECONDS}s ($(((TIMEOUT_SECONDS - elapsed) / 60))m left)"
    sleep "$POLL_SECONDS"
done
