#!/usr/bin/env bash
# Covers the two warn-only pre-commit scripts.
set -euo pipefail

index="$(mktemp)"
trap 'rm -f "$index"' EXIT

blob="$(git rev-parse HEAD:.gitignore)"

stage() {
    printf '100644 %s\t%s\n' "$blob" "$1" | GIT_INDEX_FILE="$index" git update-index --index-info
}

from_head() {
    rm -f "$index"
    GIT_INDEX_FILE="$index" git read-tree HEAD
}

run() {
    GIT_INDEX_FILE="$index" "$1"
}

fail() {
    echo "FAIL: $1" >&2
    exit 1
}

# An empty index makes every tracked file read as deleted, so the staged list runs to
# thousands of paths. A match early in a list that long can close the pipe before git
# finishes writing it, and under pipefail that has to still produce the warning.
rm -f "$index"
stage .claude/hooks/session-start.sh
output="$(run .github/scripts/check-claude-hooks.sh)"
case "$output" in
    *"reserved for env bootstrapping"*) ;;
    *) fail "a long staged list lost the .claude/hooks warning" ;;
esac

from_head
stage packages/quill/packages/primitives/src/Button.tsx
output="$(run .github/scripts/check-quill-agents-md.sh)"
case "$output" in
    *"without an AGENTS.md update"*) ;;
    *) fail "staged quill source produced no warning" ;;
esac

stage packages/quill/packages/primitives/AGENTS.md
output="$(run .github/scripts/check-quill-agents-md.sh)"
[ -z "$output" ] || fail "quill warning fired even though AGENTS.md was staged too"

from_head
stage posthog/models/team/team.py
output="$(run .github/scripts/check-claude-hooks.sh)"
[ -z "$output" ] || fail "hooks warning fired on an unrelated path"
output="$(run .github/scripts/check-quill-agents-md.sh)"
[ -z "$output" ] || fail "quill warning fired on an unrelated path"

echo "ok"
