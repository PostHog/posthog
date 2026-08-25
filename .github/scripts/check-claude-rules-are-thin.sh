#!/usr/bin/env bash
# Only Claude Code reads .claude/rules/, so a rule holding the only copy of a convention
# hides it from everyone on another agent. Rules stay short enough to be a pointer.
# Warns, never blocks: where the content belongs is a judgment a script can't make.
set -euo pipefail
BODY_LINE_BUDGET=10

for path in "$@"; do
    [ -f "$path" ] || continue
    body=$(awk 'NR==1 && /^---$/ {fm=1; next} fm && /^---$/ {fm=0; next} !fm' "$path" | grep -c '[^[:space:]]' || true)
    if [ "$body" -gt "$BODY_LINE_BUDGET" ]; then
        printf '\n\033[33mWarning: %s has %s lines of body (budget %s).\n' "$path" "$body" "$BODY_LINE_BUDGET"
        printf 'Rules are triggers, not content. Move the explanation into the nearest AGENTS.md,\n'
        printf 'a README, or a skill, and leave a pointer here. See Agent automation in AGENTS.md.\033[0m\n\n'
    fi
done
