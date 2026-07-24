#!/bin/bash
# Atomically claim the next unclaimed persona from the run directory's queue.
# Each review agent runs this as its first action; mv is atomic, so concurrent
# claimers each win exactly one persona file.
dir="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$dir/claimed"
for f in "$dir"/personas/*.md; do
  [ -e "$f" ] || continue
  name="$(basename "$f")"
  # mv errors are expected noise when losing a claim race; the post-loop check
  # distinguishes a genuinely exhausted queue from a broken run directory.
  if mv "$f" "$dir/claimed/$name" 2>/dev/null; then
    cat "$dir/claimed/$name"
    exit 0
  fi
done
if [ -n "$(ls -A "$dir/personas" 2>/dev/null)" ]; then
  echo "ERROR: claim failed: personas remain in $dir/personas but could not be moved to $dir/claimed (check permissions/mount)" >&2
else
  echo "ERROR: no persona available (queue exhausted — more claimers than personas, or claim retried)" >&2
fi
exit 1
