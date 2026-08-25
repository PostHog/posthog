#!/usr/bin/env bash
# .claude/rules/*.md files are path triggers, not documentation. Claude Code loads
# them when a file path matches; no other agent reads them at all. A rule that holds
# the only copy of a convention makes that convention invisible to everyone on Codex
# or Cursor, so the body stays short enough to be a pointer: what changed, and which
# AGENTS.md, README, or skill to read.
# Warns, never blocks -- where the content belongs is a judgment a script can't make.
set -euo pipefail
BODY_LINE_BUDGET=10

for path in "$@"; do
    [ -f "$path" ] || continue
    # Drop the YAML frontmatter, then blank lines, and count what's left.
    body=$(awk 'NR==1 && /^---$/ {fm=1; next} fm && /^---$/ {fm=0; next} !fm' "$path" | grep -c '[^[:space:]]' || true)
    if [ "$body" -gt "$BODY_LINE_BUDGET" ]; then
        printf '\n\033[33mWarning: %s has %s lines of body (budget %s).\n' "$path" "$body" "$BODY_LINE_BUDGET"
        printf 'Rules are triggers, not content. Move the explanation into the nearest AGENTS.md,\n'
        printf 'a README, or a skill, and leave a pointer here. See Agent automation in AGENTS.md.\033[0m\n\n'
    fi
done
