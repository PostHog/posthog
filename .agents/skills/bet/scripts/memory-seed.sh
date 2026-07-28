#!/usr/bin/env bash
# Memory step (d) of `/bet`: create branch bet/<slug> in the product's memory
# repo, seed bets/<slug>.md from the spec, push. Degrades gracefully (prints
# a note, exits 0) when ~/.config/foundry/memory.env is missing — memory is
# optional, never a hard requirement for running a bet.
#
# Usage: memory-seed.sh <slug> <spec.json> [--product NAME] [--dashboard-url URL]
#
# On success prints MEMORY_REPO_URL=<tokened https url> and MEMORY_BRANCH=bet/<slug> —
# pass MEMORY_REPO_URL as run_config.memory_repo_url for managed bets.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

if [ -z "${2:-}" ] || [ ! -f "$2" ]; then
    echo "Usage: memory-seed.sh <slug> <spec.json> [--product NAME] [--dashboard-url URL]" >&2
    exit 1
fi

SLUG="$1"
SPEC_FILE="$2"
shift 2
PRODUCT="${MEMORY_GIT_PRODUCT:-foundry}"
DASHBOARD_URL=""
while [ $# -gt 0 ]; do
    case "$1" in
        --product) PRODUCT="$2"; shift 2 ;;
        --dashboard-url) DASHBOARD_URL="$2"; shift 2 ;;
        *) echo "ERROR: unknown argument $1" >&2; exit 1 ;;
    esac
done

if ! memory_available; then
    echo "NOTE: ${MEMORY_ENV} not found or incomplete — skipping memory steps for '${SLUG}'."
    echo "      (this is expected/fine; memory is optional. See references/setup.md.)"
    exit 0
fi

SPEC="$(cat "$SPEC_FILE")"
CACHE_DIR="${MEMORY_CACHE_DIR:-$HOME/.cache/foundry-bet/memory-${PRODUCT}}"
REPO_URL="$(memory_repo_url "$PRODUCT")"

if [ -d "$CACHE_DIR/.git" ]; then
    git -C "$CACHE_DIR" remote set-url origin "$REPO_URL"
    git -C "$CACHE_DIR" fetch origin --quiet
    git -C "$CACHE_DIR" checkout main --quiet
    git -C "$CACHE_DIR" reset --hard origin/main --quiet
else
    mkdir -p "$(dirname "$CACHE_DIR")"
    git clone --quiet "$REPO_URL" "$CACHE_DIR"
fi
git -C "$CACHE_DIR" config user.name "${MEMORY_GIT_USER}"
git -C "$CACHE_DIR" config user.email "${MEMORY_GIT_USER}@users.noreply.foundry"

BRANCH="bet/${SLUG}"
if git -C "$CACHE_DIR" ls-remote --exit-code --heads origin "$BRANCH" >/dev/null 2>&1; then
    git -C "$CACHE_DIR" checkout -B "$BRANCH" "origin/$BRANCH" --quiet
else
    git -C "$CACHE_DIR" checkout -B "$BRANCH" main --quiet
fi

HYPOTHESIS="$(echo "$SPEC" | jq -r .hypothesis)"
METRIC_NAME="$(echo "$SPEC" | jq -r '.success_metric.name // "n/a"')"
METRIC_TARGET="$(echo "$SPEC" | jq -r '.success_metric.target // "n/a"')"
BUDGET="$(echo "$SPEC" | jq -c '.budget // {}')"
EXEC_MODE="$(echo "$SPEC" | jq -r '.execution_mode // "external"')"

{
    echo "# Bet: ${SLUG}"
    echo
    echo "**Hypothesis**: ${HYPOTHESIS}"
    echo
    echo "**Success metric**: ${METRIC_NAME} (target: ${METRIC_TARGET})"
    echo
    echo "**Guardrails**:"
    echo "$SPEC" | jq -r '(.guardrails // [])[] | "- \(.name): \(.constraint // "no constraint recorded")"'
    if [ "$(echo "$SPEC" | jq '(.guardrails // []) | length')" = "0" ]; then
        echo "- (none declared)"
    fi
    echo
    echo "**Budget**: \`${BUDGET}\`   **Execution mode**: ${EXEC_MODE}"
    echo
    if [ -n "$DASHBOARD_URL" ]; then
        echo "**Rollout KPI dashboard**: ${DASHBOARD_URL}"
        echo
    fi
    echo "**Sources**:"
    echo "$SPEC" | jq -r '(.sources // [])[] | "- \(.label)\(if .url then " (" + .url + ")" else "" end)"'
    if [ "$(echo "$SPEC" | jq '(.sources // []) | length')" = "0" ]; then
        echo "- (none recorded)"
    fi
    echo
    echo "**Built**: run in progress — this section is updated by \`/bet verdict\`."
    echo
    echo "**Verdict**: pending."
} > "$CACHE_DIR/bets/${SLUG}.md"

MAP_FILE="$CACHE_DIR/map.md"
if ! grep -q "\[\[${SLUG}\]\]" "$MAP_FILE" 2>/dev/null; then
    printf -- "- [[%s]] \xe2\x80\x94 %s\n" "$SLUG" "$HYPOTHESIS" >> "$MAP_FILE"
fi

git -C "$CACHE_DIR" add "bets/${SLUG}.md" map.md
git -C "$CACHE_DIR" commit --quiet -m "seed: bet ${SLUG}"
git -C "$CACHE_DIR" push --quiet -u origin "$BRANCH"

echo "Pushed ${BRANCH} to ${MEMORY_GIT_BASE}/${PRODUCT}.git"
echo "MEMORY_REPO_URL=${REPO_URL}"
echo "MEMORY_BRANCH=${BRANCH}"
