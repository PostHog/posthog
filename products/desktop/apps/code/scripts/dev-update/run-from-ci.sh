#!/usr/bin/env bash
# One command to try the macOS auto-update flow locally against the CI-signed
# builds, no local signing. It downloads the old (1.0.0) app and the new (2.0.0)
# feed from the latest green Code Update E2E run, serves the feed, and opens the
# old app pointed at it. In the app: open the update banner, click Download, then
# Restart, and watch the real Squirrel swap + relaunch into 2.0.0.
#
# Squirrel verifies signatures cryptographically, so the CI-signed pair updates
# here without the cert being in your keychain.
#
# Usage:
#   bash scripts/dev-update/run-from-ci.sh [run-id]
#   AUTOMATED=1 bash scripts/dev-update/run-from-ci.sh   # run the Playwright spec instead
set -euo pipefail

cd "$(dirname "$0")/../.."

command -v gh >/dev/null || {
  echo "gh (GitHub CLI) is required and must be authenticated" >&2
  exit 1
}

if pgrep -x "PostHog Code|PostHog" >/dev/null; then
  echo "PostHog is already running. Quit it first; the test build shares its single-instance lock and data dir." >&2
  exit 1
fi

RUN_ID="${1:-$(gh run list --workflow=code-update-e2e.yml --status success -L 1 --json databaseId -q '.[0].databaseId')}"
[[ -n "$RUN_ID" ]] || {
  echo "no successful Code Update E2E run found; pass a run id explicitly" >&2
  exit 1
}
echo "==> using CI run $RUN_ID"

TMP="$(mktemp -d)"
cleanup() {
  [[ -n "${SERVE_PID:-}" ]] && kill "$SERVE_PID" 2>/dev/null || true
  rm -rf "$TMP"
}
trap cleanup EXIT

echo "==> downloading signed builds from CI"
gh run download "$RUN_ID" -n update-old-build-1.0.0 -D "$TMP/old"
gh run download "$RUN_ID" -n update-new-build-2.0.0 -D "$TMP/new"

OLD_ZIP="$(find "$TMP/old" -name 'PostHog-Code-*-arm64-mac.zip' | head -1)"
FEED_YML="$(find "$TMP/new" -name latest-mac.yml | head -1)"
[[ -n "$OLD_ZIP" ]] || {
  echo "old build zip not found in artifact" >&2
  exit 1
}
[[ -n "$FEED_YML" ]] || {
  echo "latest-mac.yml not found in new build artifact" >&2
  exit 1
}

echo "==> old 1.0.0 app -> out/mac-arm64"
rm -rf out/mac-arm64 && mkdir -p out/mac-arm64
ditto -x -k "$OLD_ZIP" out/mac-arm64
xattr -dr com.apple.quarantine "out/mac-arm64/PostHog.app" 2>/dev/null || true

echo "==> new 2.0.0 feed -> out/dev-update-feed"
rm -rf out/dev-update-feed && mkdir -p out/dev-update-feed
cp "$(dirname "$FEED_YML")"/* out/dev-update-feed/

if [[ "${AUTOMATED:-}" == "1" ]]; then
  echo "==> running the automated update test"
  pnpm exec playwright test --config=tests/e2e/playwright.update.config.ts
  exit $?
fi

PORT="${PORT:-8788}"
node scripts/dev-update/serve.mjs out/dev-update-feed "$PORT" &
SERVE_PID=$!

APP_LOG="out/run-from-ci-app.log"
echo
echo "==> launching PostHog 1.0.0 (feed http://127.0.0.1:$PORT)"
echo "    In the app: open the update banner, click Download, then Restart."
echo "    It swaps and relaunches into 2.0.0. Quit the app (or Ctrl+C) to finish."
echo "    App output: $APP_LOG   update log: ~/.posthog-code/logs/main.log"
echo
POSTHOG_E2E_UPDATE_FEED="http://127.0.0.1:$PORT" \
  "out/mac-arm64/PostHog.app/Contents/MacOS/PostHog" >"$APP_LOG" 2>&1 || true

echo "==> app exited; cleaning up"
