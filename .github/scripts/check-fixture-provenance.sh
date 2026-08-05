#!/usr/bin/env bash
# Warns when a commit adds a batch of new conversation-shaped case data to an eval
# or fixture file. That is the moment fixture provenance matters: sample data that
# reads like a real support conversation is either invented, or it is a customer's
# words on a public repo.
#
# Warning only, never blocks — "was this text derived from a real conversation" is
# not mechanically decidable. The job here is to make a reviewer look at the diff.
#
# Calibrated per file, which is how lint-staged invokes this. Against the 60 most
# recent commits touching eval/fixture paths, 265 matched files had 3 files with
# any hit at all (1, 3, and 13), so the threshold below is 2 rather than 1: two
# conversation-shaped strings in one file is meaningfully more than one stray
# "message" field, and dropping from 3 to 2 costs nothing measured. The incident
# this was built from scores 34 in a single file, well clear of the threshold.
# Re-run that measurement before loosening anything below.
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

[ $# -gt 0 ] || exit 0

hits=$(git diff --cached -U0 -- "$@" | grep -cE "$PATTERN" || true)
[ "$hits" -ge "$THRESHOLD" ] || exit 0

printf '\n\033[33mWarning: this commit adds %s blocks of conversation-shaped case data.\n\n' "$hits" >&2
printf 'If any of it came from a real conversation, ticket, or log, it does not belong in a\n' >&2
printf 'public repo — and renaming the people, hosts, and identifiers does not clear it. The\n' >&2
printf 'prose, typos, error IDs, and order of events are still the customer'"'"'s.\n\n' >&2
printf 'Write sample data by listing the properties a case has to exercise, then writing the\n' >&2
printf 'case from that list with the real material closed. Do not claim "written fresh" in a\n' >&2
printf 'commit message unless that is what you did.\n\n' >&2
printf 'See ee/hogai/eval/AGENTS.md and AGENTS.md "Public open source repo guidance".\033[0m\n\n' >&2
