#!/usr/bin/env bash
# AGENTS.md is the canonical agent-instructions file; CLAUDE.md is always a
# symlink to its sibling AGENTS.md (and every AGENTS.md has one). Fix with:
#   ln -s AGENTS.md <dir>/CLAUDE.md
# Everything is checked against the git index so a missing `git add` is caught
# before commit, not only on a fresh CI checkout.
set -euo pipefail
status=0
tracked=" $(git ls-files '*AGENTS.md' '*CLAUDE.md' | tr '\n' ' ') "
err() { echo "::error file=$1::$2"; status=1; }

# Every tracked CLAUDE.md is a symlink (mode 120000) to its sibling AGENTS.md,
# and that sibling is itself tracked (no dangling links).
while read -r mode _ _ path; do
    sibling="${path%CLAUDE.md}AGENTS.md"
    if [ "$mode" != 120000 ] || [ "$(git cat-file -p ":$path")" != AGENTS.md ]; then
        err "$path" "CLAUDE.md must be a symlink to its sibling AGENTS.md"
    elif [[ "$tracked" != *" $sibling "* ]]; then
        err "$path" "CLAUDE.md symlink has no tracked sibling AGENTS.md"
    fi
done < <(git ls-files -s '*CLAUDE.md')

# Every tracked AGENTS.md has that sibling CLAUDE.md tracked alongside it.
while read -r path; do
    sibling="${path%AGENTS.md}CLAUDE.md"
    [[ "$tracked" == *" $sibling "* ]] ||
        err "$path" "AGENTS.md needs a sibling CLAUDE.md symlink (ln -s AGENTS.md $sibling)"
done < <(git ls-files '*AGENTS.md')

exit $status
