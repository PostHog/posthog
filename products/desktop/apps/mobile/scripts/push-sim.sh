#!/usr/bin/env bash
# Send a fake push to the booted iOS simulator. No Expo, no APNs, no token.
# Requires Xcode tools (`xcrun simctl` ships with Xcode).
#
# Usage:  ./scripts/push-sim.sh ["Title"] ["Body"] [taskId] [taskRunId]
# All args optional; defaults to a generic test push.

set -euo pipefail

BUNDLE_ID="com.posthog.code.mobile"
TITLE="${1:-PostHog}"
BODY="${2:-Test push — tap me}"
TASK_ID="${3:-00000000-0000-0000-0000-000000000000}"
TASK_RUN_ID="${4:-00000000-0000-0000-0000-000000000000}"

# Verify a simulator is booted.
if ! xcrun simctl list devices booted | grep -q "Booted"; then
  echo "ERROR: no booted simulator. Start one with: pnpm --filter @posthog/mobile ios" >&2
  exit 1
fi

PAYLOAD=$(mktemp -t push-sim.XXXXXX.json)
trap 'rm -f "$PAYLOAD"' EXIT

cat > "$PAYLOAD" <<EOF
{
  "aps": {
    "alert": { "title": "$TITLE", "body": "$BODY" },
    "sound": "default"
  },
  "data": {
    "taskId": "$TASK_ID",
    "taskRunId": "$TASK_RUN_ID"
  }
}
EOF

xcrun simctl push booted "$BUNDLE_ID" "$PAYLOAD"
echo "Sent: \"$TITLE\" → $BUNDLE_ID (booted simulator)"
