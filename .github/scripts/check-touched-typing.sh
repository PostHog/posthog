#!/usr/bin/env bash
# Warn when the staged diff adds or edits Python functions without full annotations.
# Never blocks: an edit to old code should not have to annotate its callers to land.
#
# A warn-only check has to live in the pre-commit hook body. As a lint-staged task it
# would print nothing, because lint-staged discards the output of every task that
# exits 0.
set -uo pipefail

script="$(dirname "$0")/check_touched_typing.py"
[ -f "$script" ] || exit 0
git diff --cached --quiet -- 'posthog/*.py' 'ee/*.py' 'products/*.py' 'common/*.py' && exit 0

# The script parses the repo's Python, which uses syntax an older system python3 rejects,
# so prefer the project venv. worktree-borrow sets VIRTUAL_ENV in a light worktree.
python=""
for candidate in "${VIRTUAL_ENV:+$VIRTUAL_ENV/bin/python}" .flox/cache/venv/bin/python; do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then
        python="$candidate"
        break
    fi
done
[ -n "$python" ] || python="$(command -v python3 || true)"
[ -n "$python" ] || exit 0
"$python" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2> /dev/null || exit 0

"$python" "$script" --staged || true
