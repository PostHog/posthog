#!/usr/bin/env bash
# One status line per PR, for the ship-it-factory loop.
#
# Usage: pr_status.sh [--label stamphog] <pr>...
# Output columns: pr state draft mergeable ci review label url
#   ci     = pass | fail | pending   (required checks only; no required checks yet = pending)
#   review = reviewDecision (APPROVED, REVIEW_REQUIRED, CHANGES_REQUESTED, or none)
#   label  = yes when the trigger label is on the PR
set -uo pipefail

label="stamphog"
if [ "${1:-}" = "--label" ]; then
    label="$2"
    shift 2
fi

printf '%-8s %-7s %-6s %-12s %-8s %-18s %-6s %s\n' pr state draft mergeable ci review label url
for pr in "$@"; do
    meta=$(gh pr view "$pr" --json state,isDraft,mergeable,reviewDecision,labels,url \
        --jq "[.state, (.isDraft|tostring), .mergeable, (if .reviewDecision == \"\" or .reviewDecision == null then \"none\" else .reviewDecision end), (if any(.labels[]; .name == \"$label\") then \"yes\" else \"no\" end), .url] | @tsv")
    buckets=$(gh pr checks "$pr" --required --json bucket --jq '.[].bucket' 2>/dev/null | sort -u | tr '\n' ' ')
    if [ -z "$buckets" ]; then
        ci="pending"
    elif echo "$buckets" | grep -qE 'fail|cancel'; then
        ci="fail"
    elif echo "$buckets" | grep -q 'pending'; then
        ci="pending"
    else
        ci="pass"
    fi
    IFS=$'\t' read -r state draft mergeable review has_label url <<<"$meta"
    printf '%-8s %-7s %-6s %-12s %-8s %-18s %-6s %s\n' "$pr" "$state" "$draft" "$mergeable" "$ci" "$review" "$has_label" "$url"
done
