#!/usr/bin/env bash
# Resolve a complete change set against MERGE_TARGET without fetching history.
set -uo pipefail

# An API failure or a truncated file list has to widen to ALL
# rather than upload a partial file list, which Trunk cannot
# distinguish from a complete one. The computation step reads
# `resolved` and reports ALL when it is anything but true.
unresolved() {
    echo "::warning::$1; reporting ALL."
    echo 'resolved=false' >> "$GITHUB_OUTPUT"
    exit 0
}

# Each attempt overwrites the output file, so a failed attempt
# leaves no partial page behind for the next one to append to.
# A 4xx, rate limits included, would fail again on the same
# token bucket, so only network errors and 5xx are retried.
gh_api_to() {
    local out="$1" err="$RUNNER_TEMP/gh-api-error.txt" attempt
    shift
    for attempt in 1 2 3; do
        if gh api "$@" > "$out" 2> "$err"; then
            return 0
        fi
        cat "$err" >&2
        grep -qE '\(HTTP 4[0-9]{2}\)' "$err" && return 1
        [ "$attempt" -lt 3 ] && sleep $((attempt * 5))
    done
    return 1
}

# A renamed file is listed as its old path and its new one. The
# old path is what the target script reads as deleted, and it
# widens on that: the tach map has no importer edge for it.
file_paths='.filename, (select(.previous_filename) | .previous_filename)'

[[ -n "$MERGE_TARGET" && ! "$MERGE_TARGET" =~ ^0+$ ]] || unresolved "No valid comparison base"

head_sha="$(git rev-parse HEAD)"
compare="$RUNNER_TEMP/compare.json"
gh_api_to "$compare" "repos/$REPOSITORY/compare/$MERGE_TARGET...$head_sha?per_page=1" \
    || unresolved "The compare API failed for $MERGE_TARGET...$head_sha"

merge_base="$(jq -r '.merge_base_commit.sha // empty' "$compare")"
[[ "$merge_base" =~ ^[0-9a-f]{40}$ ]] || unresolved "The compare API returned no merge base"
jq -e '.files | type == "array"' "$compare" > /dev/null || unresolved "The compare API returned no file list"

# The compare API lists at most 300 files. Past that, the merge
# base commit is fetched without blobs and diffed against the
# checked-out merge commit, which needs only their trees. The pull
# request files API is no substitute: it describes the PR head
# against its own base, and reads whatever head the PR has now.
if [ "$(jq '.files | length' "$compare")" -lt 300 ]; then
    jq -r ".files[] | $file_paths" "$compare" > "$RUNNER_TEMP/listed-files.txt"
else
    git fetch --no-tags --depth=1 --filter=blob:none origin "$merge_base" \
        || unresolved "Could not fetch the merge base $merge_base"
    git diff --name-only --no-renames "$merge_base" HEAD > "$RUNNER_TEMP/listed-files.txt" \
        || unresolved "Could not diff against the merge base"
fi

sort -u "$RUNNER_TEMP/listed-files.txt" > "$RUNNER_TEMP/changed-files.txt"
sed 's/^/  /' "$RUNNER_TEMP/changed-files.txt"
changed="$(cat "$RUNNER_TEMP/changed-files.txt")"

echo 'resolved=true' >> "$GITHUB_OUTPUT"
echo "merge_base=$merge_base" >> "$GITHUB_OUTPUT"
if printf '%s\n' "$changed" | grep -qE '^(rust|proto)/'; then
    echo 'rust_affected=true' >> "$GITHUB_OUTPUT"
fi
if printf '%s\n' "$changed" | grep -qxF 'pnpm-lock.yaml'; then
    echo 'js_lockfile_changed=true' >> "$GITHUB_OUTPUT"
fi
