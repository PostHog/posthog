#!/usr/bin/env bash
# Warns when the staged diff adds a high share of comment lines. Agents narrate code
# and record change history in comments, and a commit is the cheapest moment to
# trim them: before a reviewer reads the diff and before the CI report flags it.
#
# Warning only, never blocks. The same classifier as the pull request check
# (.github/scripts/check_comment_density.py) runs over the staged diff, with the same
# thresholds, so the two agree on a diff.
#
# A warn-only check has to live in the pre-commit hook body. As a lint-staged task it
# would print nothing, because lint-staged discards the output of every task that
# exits 0.
set -uo pipefail

script="$(dirname "$0")/check_comment_density.py"
[ -f "$script" ] || exit 0
command -v python3 > /dev/null 2>&1 || exit 0

# GITHUB_OUTPUT switches the classifier to its CI output mode; unset it so the
# result comes back on stdout as `status=<ok|warn|alert> <summary>` and a body.
report=$(git diff --cached -U0 --no-color | GITHUB_OUTPUT='' python3 "$script" 2> /dev/null) || exit 0
status=$(printf '%s\n' "$report" | head -n1 | sed -n 's/^status=\([a-z]*\) .*/\1/p')
[ "$status" = "warn" ] || [ "$status" = "alert" ] || exit 0

summary=$(printf '%s\n' "$report" | head -n1 | sed 's/^status=[a-z]* //')
# The backticks are literal markdown from the report body, not an expansion.
# shellcheck disable=SC2016
files=$(printf '%s\n' "$report" | sed -n 's/^| `\([^`]*\)` | \([0-9]*\) | \([0-9]*\) |$/  \1 (\2 of \3)/p')

printf '\n\033[33mWarning: %s in this commit.\n' "$summary" >&2
if [ -n "$files" ]; then
    printf '\nFiles with the most added comment lines:\n%s\n' "$files" >&2
fi
printf '\nComments that restate the code, record how the change came about, or narrate the\n' >&2
printf 'next line add noise for the next reader. Keep the ones that explain a reason the code\n' >&2
printf 'cannot show, and remove the rest. See .agents/skills/writing-code-comments/SKILL.md.\033[0m\n\n' >&2
