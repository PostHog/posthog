#!/usr/bin/env bash
# Memory step of `/bet verdict`: update the bet's memory entry with the
# verdict FIRST (so it lands wherever the verdict sends it), then run the
# real git choreography for that verdict:
#   promoted     -> merge bet/<slug> into main, no-ff
#   rolled_back  -> tag archive/<slug>, extract the learning entry onto main
#   iterate      -> branch stays as-is, nothing further
#
# Usage: memory-verdict.sh <slug> <promoted|rolled_back|iterate> [reasoning] [--product NAME]
# Degrades gracefully (prints a note, exits 0) when memory.env is missing.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

if [ -z "${2:-}" ]; then
    echo "Usage: memory-verdict.sh <slug> <promoted|rolled_back|iterate> [reasoning] [--product NAME]" >&2
    exit 1
fi
SLUG="$1"
VERDICT="$2"
shift 2
REASONING=""
PRODUCT="${MEMORY_GIT_PRODUCT:-foundry}"
if [ $# -gt 0 ] && [ "$1" != "--product" ]; then
    REASONING="$1"
    shift
fi
while [ $# -gt 0 ]; do
    case "$1" in
        --product) PRODUCT="$2"; shift 2 ;;
        *) echo "ERROR: unknown argument $1" >&2; exit 1 ;;
    esac
done

case "$VERDICT" in
    promoted|rolled_back|iterate) ;;
    *) echo "ERROR: verdict must be promoted, rolled_back, or iterate (got '${VERDICT}')" >&2; exit 1 ;;
esac

if ! memory_available; then
    echo "NOTE: ${MEMORY_ENV} not found or incomplete — skipping memory choreography for '${SLUG}'."
    exit 0
fi

CACHE_DIR="${MEMORY_CACHE_DIR:-$HOME/.cache/foundry-bet/memory-${PRODUCT}}"
REPO_URL="$(memory_repo_url "$PRODUCT")"
BRANCH="bet/${SLUG}"

if [ ! -d "$CACHE_DIR/.git" ]; then
    echo "ERROR: no local clone at ${CACHE_DIR} — run memory-seed.sh for '${SLUG}' first." >&2
    exit 1
fi
git -C "$CACHE_DIR" remote set-url origin "$REPO_URL"
git -C "$CACHE_DIR" fetch origin --quiet
git -C "$CACHE_DIR" config user.name "${MEMORY_GIT_USER}"
git -C "$CACHE_DIR" config user.email "${MEMORY_GIT_USER}@users.noreply.foundry"
git -C "$CACHE_DIR" checkout -B "$BRANCH" "origin/$BRANCH" --quiet

BET_FILE="bets/${SLUG}.md"
VERDICT_LINE="**Verdict**: ${VERDICT}"
if [ -n "$REASONING" ]; then
    VERDICT_LINE="${VERDICT_LINE} — ${REASONING}"
fi
if grep -q '\*\*Verdict\*\*: pending\.' "$CACHE_DIR/$BET_FILE" 2>/dev/null; then
    # Portable in-place sed for both GNU and BSD sed: write to a temp file.
    sed "s|\*\*Verdict\*\*: pending\.|${VERDICT_LINE//|/\\|}|" "$CACHE_DIR/$BET_FILE" > "$CACHE_DIR/$BET_FILE.tmp"
    mv "$CACHE_DIR/$BET_FILE.tmp" "$CACHE_DIR/$BET_FILE"
else
    printf '\n%s\n' "$VERDICT_LINE" >> "$CACHE_DIR/$BET_FILE"
fi
git -C "$CACHE_DIR" add "$BET_FILE"
git -C "$CACHE_DIR" commit --quiet -m "record verdict: ${SLUG} -> ${VERDICT}" --allow-empty
git -C "$CACHE_DIR" push --quiet -u origin "$BRANCH"
echo "Recorded verdict on ${BRANCH} (memory entry updated before any merge/archive)."

case "$VERDICT" in
    promoted)
        git -C "$CACHE_DIR" checkout main --quiet
        git -C "$CACHE_DIR" reset --hard origin/main --quiet
        MSG="promote: ${SLUG}"
        if [ -n "$REASONING" ]; then MSG="${MSG} — ${REASONING}"; fi
        git -C "$CACHE_DIR" merge --no-ff "$BRANCH" -m "$MSG" --quiet
        git -C "$CACHE_DIR" push --quiet origin main
        echo "Merged ${BRANCH} into main (promoted)."
        ;;
    rolled_back)
        git -C "$CACHE_DIR" tag -f "archive/${SLUG}" "$BRANCH"
        git -C "$CACHE_DIR" push --quiet origin "refs/tags/archive/${SLUG}"
        git -C "$CACHE_DIR" checkout main --quiet
        git -C "$CACHE_DIR" reset --hard origin/main --quiet
        git -C "$CACHE_DIR" checkout "$BRANCH" -- "$BET_FILE"
        if ! grep -q "\[\[${SLUG}\]\]" "$CACHE_DIR/map.md" 2>/dev/null; then
            printf -- "- [[%s]] \xe2\x80\x94 rolled back, learning extracted\n" "$SLUG" >> "$CACHE_DIR/map.md"
            git -C "$CACHE_DIR" add map.md
        fi
        git -C "$CACHE_DIR" add "$BET_FILE"
        git -C "$CACHE_DIR" commit --quiet -m "learn: ${SLUG} rolled back — extract the learning onto main"
        git -C "$CACHE_DIR" push --quiet origin main
        echo "Tagged archive/${SLUG}; extracted the learning entry onto main (branch kept, not merged)."
        ;;
    iterate)
        echo "Branch ${BRANCH} stays as-is for the next iteration."
        ;;
esac
