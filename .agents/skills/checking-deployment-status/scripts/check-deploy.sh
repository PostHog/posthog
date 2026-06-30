#!/usr/bin/env bash
# Check whether a PostHog PR or commit has deployed to dev / prod-us / prod-eu.
#
# Usage:
#   check-deploy.sh <pr-number>
#   check-deploy.sh <commit-sha>
#
# Read-only: queries the GitHub Deployments + compare APIs via `gh`. Deploys are
# batched, so it asks "is my commit an ancestor of what's deployed?" rather than
# matching the merge SHA exactly.
set -euo pipefail

REPO="PostHog/posthog"
ENVS=("dev" "prod-us" "prod-eu")

arg="${1:-}"
if [[ -z "$arg" ]]; then
  echo "Usage: check-deploy.sh <pr-number|commit-sha>" >&2
  exit 2
fi

# Resolve the input to a full commit SHA.
if [[ "$arg" =~ ^[0-9]+$ ]]; then
  info=$(gh pr view "$arg" --repo "$REPO" \
    --json state,mergedAt,mergeCommit \
    --jq '[.state, (.mergedAt // "null"), (.mergeCommit.oid // "null")] | @tsv')
  pr_state=$(cut -f1 <<<"$info")
  pr_merged=$(cut -f2 <<<"$info")
  sha=$(cut -f3 <<<"$info")
  if [[ "$pr_state" != "MERGED" || "$sha" == "null" ]]; then
    echo "PR #$arg is $pr_state — not merged, so nothing to deploy yet."
    exit 0
  fi
  echo "PR #$arg merged at $pr_merged"
  echo "Merge commit: $sha"
else
  sha="$arg"
fi

echo
echo "Deployment status for ${sha:0:12}:"
for env in "${ENVS[@]}"; do
  deployed=$(gh api "repos/$REPO/deployments?environment=$env&per_page=1" \
    --jq '.[0].sha // empty' 2>/dev/null || true)
  if [[ -z "$deployed" ]]; then
    echo "  $env: no deployments found"
    continue
  fi
  cmp=$(gh api "repos/$REPO/compare/$sha...$deployed" --jq '.status' 2>/dev/null || echo "error")
  case "$cmp" in
    identical|ahead) verdict="✅ DEPLOYED" ;;
    behind|diverged) verdict="⏳ not yet" ;;
    *)               verdict="? unknown ($cmp)" ;;
  esac
  echo "  $env: $verdict (env at ${deployed:0:12})"
done
