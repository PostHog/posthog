#!/usr/bin/env bash
# Bring one PR's files from the backup stash into a clean tree, then stage them.
#
# Usage: extract_group.sh <stash-ref> <file>...
#   A file in the stash commit is checked out from it (modified or staged-new file).
#   A file only in the stash's untracked part (<stash>^3) is checked out from there.
#   A file in neither is a deletion, so it is removed with `git rm`.
# Run it on a clean tree at the PR's base (origin/master, or the branch below in a stack).
set -euo pipefail

if [ "$#" -lt 2 ]; then
    echo "usage: $0 <stash-ref> <file>..." >&2
    exit 2
fi
stash="$1"
shift

has_untracked=0
git rev-parse --verify -q "${stash}^3" >/dev/null && has_untracked=1

for f in "$@"; do
    if git cat-file -e "${stash}:${f}" 2>/dev/null; then
        git checkout "$stash" -- "$f"
    elif [ "$has_untracked" = 1 ] && git cat-file -e "${stash}^3:${f}" 2>/dev/null; then
        git checkout "${stash}^3" -- "$f"
    elif git cat-file -e "HEAD:${f}" 2>/dev/null; then
        git rm -q -- "$f"
    else
        echo "not in backup and not in HEAD: $f" >&2
        exit 1
    fi
done

git add -A -- "$@" 2>/dev/null || true
git status --short
