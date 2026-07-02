#!/bin/bash
# Print the PR's removed/renamed file paths (one per line) from the GitHub PR-files API.
# "removed"/"renamed" files existed on the PR base, so they are historical (renames carry
# the old path in previous_filename). Consumers filter these for deleted Django migrations
# (hogli lint:migration-deletions). Retries transient gh-api errors. Requires REPO,
# PR_NUMBER, and an authenticated gh (GH_TOKEN or ambient token).
set -euo pipefail

for attempt in 1 2 3; do
    if removed=$(gh api --paginate "repos/${REPO}/pulls/${PR_NUMBER}/files?per_page=100" \
          --jq '.[] | select(.status == "removed" or .status == "renamed") | .previous_filename // .filename'); then
        printf '%s\n' "$removed"
        exit 0
    fi
    if [ "$attempt" = 3 ]; then
        echo "could not list PR files after 3 attempts" >&2
        exit 1
    fi
    echo "gh api attempt ${attempt} failed; retrying" >&2
    sleep $((attempt * 5))
done
