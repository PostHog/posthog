#!/usr/bin/env bash
# Warn when a commit touches .claude/hooks/. Never blocks: a SessionStart hook is a
# legitimate change, and only the author knows which kind this one is.
#
# A warn-only check has to live in the pre-commit hook body. As a lint-staged task it
# would print nothing, because lint-staged discards the output of every task that
# exits 0.
set -uo pipefail

# The staged list is captured before it is matched. Piping it into `grep -q` lets grep
# exit at the first match, which can leave the writer with SIGPIPE, and under pipefail
# the whole pipeline then reads as failed and the warning never prints.
staged=$(git diff --cached --name-only)

if grep -q '^\.claude/hooks/' <<< "$staged"; then
    printf "\n\033[33mWarning: hooks in .claude/ are reserved for env bootstrapping (SessionStart only).\n"
    printf "Prefer skills, AGENTS.md instructions, or lint-staged rules. See Agent automation in AGENTS.md.\033[0m\n\n"
fi
