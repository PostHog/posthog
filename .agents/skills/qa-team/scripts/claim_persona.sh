#!/bin/bash
# Atomically claim the next unclaimed persona from the run directory's queue.
# Each review agent runs this as its first action; mv is atomic, so concurrent
# claimers each win exactly one persona file.
dir="$(cd "$(dirname "$0")" && pwd)"
for f in "$dir"/personas/*.md; do
  [ -e "$f" ] || continue
  name="$(basename "$f")"
  if mv "$f" "$dir/claimed/$name" 2>/dev/null; then
    cat "$dir/claimed/$name"
    exit 0
  fi
done
echo "ERROR: no persona available" >&2
exit 1
