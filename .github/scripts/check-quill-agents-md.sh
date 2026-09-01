#!/usr/bin/env bash
# Warn when quill component sources change without an AGENTS.md update. The consumer
# guide is how other teams pick the right component, so it goes stale silently.
# Never blocks: not every source change alters the consumer contract.
#
# Runs from .husky/pre-commit rather than as a lint-staged task because lint-staged
# discards the output of every task that exits 0, so a warn-only task there prints
# nothing at all.
set -uo pipefail

staged=$(git diff --cached --name-only)

if printf '%s\n' "$staged" | grep -qE '^packages/quill/packages/[^/]+/src/.*\.(ts|tsx|css)$' \
    && ! printf '%s\n' "$staged" | grep -qE '^packages/quill/.*AGENTS\.md$'; then
    printf "\n\033[33mWarning: quill component sources changed without an AGENTS.md update.\n"
    printf "If variants, composition, or spacing changed, update the consumer guide\n"
    printf "(packages/quill/packages/<pkg>/AGENTS.md) in the same PR.\033[0m\n\n"
fi
