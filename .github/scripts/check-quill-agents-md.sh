#!/usr/bin/env bash
# Warn when quill component sources change without an AGENTS.md update. The consumer
# guide is how other teams pick the right component, so it goes stale silently.
# Never blocks: not every source change alters the consumer contract.
#
# A warn-only check has to live in the pre-commit hook body. As a lint-staged task it
# would print nothing, because lint-staged discards the output of every task that
# exits 0.
set -uo pipefail

# The staged list is captured before it is matched. Piping it into `grep -q` lets grep
# exit at the first match, which can leave the writer with SIGPIPE, and under pipefail
# the whole pipeline then reads as failed and the warning never prints.
staged=$(git diff --cached --name-only)

# A package's consumer guide is its own AGENTS.md or, where the guide is split by topic,
# any doc under its own src/docs/. The workspace AGENTS.md covers every package. A doc
# in a different package does not count.
packages=$(grep -oE '^packages/quill/packages/[^/]+/src/.*\.(ts|tsx|css)$' <<< "$staged" | cut -d/ -f4 | sort -u)
stale=""
for pkg in $packages; do
    if ! grep -qE "^packages/quill/(AGENTS\.md|packages/$pkg/(AGENTS\.md|src/docs/[^/]+\.md))$" <<< "$staged"; then
        stale="$stale $pkg"
    fi
done

if [ -n "$stale" ]; then
    printf "\n\033[33mWarning: quill component sources changed without an AGENTS.md update (%s).\n" "${stale# }"
    printf "If variants, composition, or spacing changed, update the consumer guide\n"
    printf "(packages/quill/packages/<pkg>/AGENTS.md, or a topic doc under its src/docs/) in the same PR.\033[0m\n\n"
fi
