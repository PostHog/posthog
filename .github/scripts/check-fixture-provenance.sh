#!/usr/bin/env bash
# Warns when a commit adds a batch of new conversation-shaped case data to an eval
# or fixture file. That is the moment fixture provenance matters: sample data that
# reads like a real support conversation is either invented, or it is a customer's
# words on a public repo.
#
# Warning only, never blocks — "was this text derived from a real conversation" is
# not mechanically decidable. The job here is to make a reviewer look at the diff.
#
# Called from .husky/pre-commit rather than as a lint-staged task. lint-staged hides
# the output of a task that succeeds unless it runs with --verbose, so a
# warning-only task there prints nothing at exactly the moment it fires.
#
# Counted per file, and the threshold applies per file: two separate fixtures with
# one match each are not the pattern this looks for. Calibrated against the 60 most
# recent commits touching eval/fixture paths — of 265 matched files, 3 had any hit
# at all — so the threshold is 2 rather than 1, and the incident this was built
# from scores 34 in a single file. Re-run that measurement before loosening it.
set -euo pipefail

# A content-bearing key holding a substantial string, in the four shapes fixtures
# use here: a message dict, a message constructor, a Python keyword argument, and
# the multiline `body=(` concatenation that ticket fixtures are written in.
# Short values ("role": "human", "text": []) are structure, not prose.
#
# The keyword-argument arm covers `content` and `body` only, deliberately. Those
# name what a person said or wrote. `prompt` and `text` name what we send a model,
# and including them fires on roughly one in eight eval edits, which trains the
# warning out. Measured: `content|body` fires on 3 of 265 files, adding all five
# keys fires on 35.
readonly PATTERN='^\+.*("(content|message|body|text|prompt)"[[:space:]]*:[[:space:]]*"[^"]{25,}|(Human|Assistant|User|System)Message\([^)]*"[^"]{25,}|(body|content)[[:space:]]*=[[:space:]]*(\(|"""|"[^"]{25,}))'
readonly THRESHOLD=2
readonly PATHS='(^|/)(eval|evals|fixtures)/.*\.(py|json|jsonl|md)$'

# The files named, or every staged eval/fixture file when called with none.
if [ $# -gt 0 ]; then
    candidates=$(printf '%s\n' "$@" | grep -E "$PATHS" || true)
else
    candidates=$(git diff --cached --name-only --diff-filter=ACM | grep -E "$PATHS" || true)
fi
[ -n "$candidates" ] || exit 0

flagged=""
# Heredoc rather than a pipe: a piped `while` runs in a subshell in some shells,
# which would discard everything appended to `flagged`.
while IFS= read -r file; do
    [ -n "$file" ] || continue
    hits=$(git diff --cached -U0 -- "$file" | grep -cE "$PATTERN" || true)
    [ "$hits" -ge "$THRESHOLD" ] || continue
    flagged="$flagged  $file ($hits)
"
done <<EOF
$candidates
EOF

[ -n "$flagged" ] || exit 0

printf '\n\033[33mWarning: these files gain conversation-shaped case data in this commit.\n\n' >&2
printf '%s\n' "$flagged" >&2
printf 'If any of it came from a real conversation, ticket, or log, it does not belong in a\n' >&2
printf 'public repo — and renaming the people, hosts, and identifiers does not clear it. The\n' >&2
printf 'prose, typos, error IDs, and order of events are still the customer'"'"'s.\n\n' >&2
printf 'Write sample data by listing the properties a case has to exercise, then writing the\n' >&2
printf 'case from that list with the real material closed. Do not claim "written fresh" in a\n' >&2
printf 'commit message unless that is what you did.\n\n' >&2
printf 'See ee/hogai/eval/AGENTS.md and AGENTS.md "Public open source repo guidance".\033[0m\n\n' >&2
