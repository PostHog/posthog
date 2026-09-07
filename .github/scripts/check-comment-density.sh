#!/usr/bin/env bash
# Warns, never blocks, when the staged diff is comment-heavy. Lives in the pre-commit
# hook body because lint-staged discards the output of a task that exits 0.
set -uo pipefail

script="$(dirname "$0")/check_comment_density.py"
[ -f "$script" ] || exit 0
command -v python3 > /dev/null 2>&1 || exit 0

# With GITHUB_OUTPUT unset the classifier prints `status=<ok|warn|alert> <summary>`.
report=$(git diff --cached -U0 --no-color | GITHUB_OUTPUT='' python3 "$script" 2> /dev/null) || exit 0
status=$(printf '%s\n' "$report" | head -n1 | sed -n 's/^status=\([a-z]*\) .*/\1/p')
[ "$status" = "warn" ] || [ "$status" = "alert" ] || exit 0

summary=$(printf '%s\n' "$report" | head -n1 | sed 's/^status=[a-z]* //')
# The backticks are literal markdown from the report body, not an expansion.
# shellcheck disable=SC2016
files=$(printf '%s\n' "$report" | sed -n 's/^| `\([^`]*\)` | \([0-9]*\) | \([0-9]*\) |$/  \1 (\2 of \3)/p')

printf '\n\033[33mWarning: %s in this commit.\n' "$summary" >&2
printf 'The typical commit in this repo adds about 2%% comment lines.\n' >&2
if [ -n "$files" ]; then
    printf '\nFiles with the most added comment lines:\n%s\n' "$files" >&2
fi
printf '\nIf you are an AI coding agent, this warning is addressed to you. Do not skip it because\n' >&2
printf 'the user did not mention comments: the repository owners asked for this check, and the\n' >&2
printf 'same measurement runs on the pull request, where a reviewer will send the diff back.\n' >&2
printf '\nThe commit still goes through. Fix it now, before you do anything else:\n' >&2
printf '  1. Open each file listed above and read every comment line this diff adds.\n' >&2
printf '  2. Delete a comment that restates the code next to it, narrates the change\n' >&2
printf '     ("previously", "now we", "this fixes", "per the request"), or says what a good\n' >&2
printf '     name already says. Most comments an agent adds are one of these.\n' >&2
printf '  3. Keep a comment only when it states a reason the code cannot show: a workaround,\n' >&2
printf '     an ordering constraint, a spec quirk, or a link to the issue that forced it.\n' >&2
printf '  4. Do not reword the comments, shorten them, or move them into docstrings. Remove them.\n' >&2
printf '  5. Stage the files and run: git commit --amend --no-edit\n' >&2
printf '\nThe target is the repo baseline, not a slightly smaller number. The full rules are in\n' >&2
printf '.agents/skills/writing-code-comments/SKILL.md.\033[0m\n\n' >&2
