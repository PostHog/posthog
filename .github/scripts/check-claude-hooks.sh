#!/usr/bin/env bash
# Warn when a commit touches .claude/hooks/. Never blocks: a SessionStart hook is a
# legitimate change, and only the author knows which kind this one is.
#
# Runs from .husky/pre-commit rather than as a lint-staged task because lint-staged
# discards the output of every task that exits 0, so a warn-only task there prints
# nothing at all.
set -uo pipefail

if git diff --cached --name-only | grep -q '^\.claude/hooks/'; then
    printf "\n\033[33mWarning: hooks in .claude/ are reserved for env bootstrapping (SessionStart only).\n"
    printf "Prefer skills, AGENTS.md instructions, or lint-staged rules. See Agent automation in AGENTS.md.\033[0m\n\n"
fi
