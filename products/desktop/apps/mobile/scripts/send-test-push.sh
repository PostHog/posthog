#!/usr/bin/env bash
# Send a test push to your dev device through Expo's push service.
# Usage:
#   ./scripts/send-test-push.sh
#
# Paste your token into TOKEN below ONCE. After that just run the script.
# Edit TITLE / BODY / TASK_ID / TASK_RUN_ID as needed.

set -euo pipefail

# ─── EDIT THIS ─────────────────────────────────────────────────────────────
TOKEN="ExponentPushToken[PASTE_YOUR_TOKEN_HERE]"
TITLE="PostHog"
BODY="Test push — tap me"
# These two fields are required by the app to navigate when the user taps
# the notification (see notifications.ts:111). Use a real taskId + taskRunId
# from your account if you want the tap to open a real screen.
TASK_ID="00000000-0000-0000-0000-000000000000"
TASK_RUN_ID="00000000-0000-0000-0000-000000000000"
# ───────────────────────────────────────────────────────────────────────────

if [[ "$TOKEN" == *"PASTE_YOUR_TOKEN_HERE"* ]]; then
  echo "ERROR: edit TOKEN in $(basename "$0") first." >&2
  exit 1
fi

if [[ "$TOKEN" != ExponentPushToken\[* ]]; then
  echo "ERROR: token should look like ExponentPushToken[xxx]. Got: $TOKEN" >&2
  exit 1
fi

echo "Sending push…"

# Send the push. -s silences progress, --fail-with-body returns non-zero on
# HTTP errors but still prints the body so we can see the reason.
RESP=$(
  curl -sS --fail-with-body \
    -H "Content-Type: application/json" \
    -H "Accept: application/json" \
    -H "Accept-Encoding: gzip, deflate" \
    -X POST https://exp.host/--/api/v2/push/send \
    -d "$(cat <<EOF
{
  "to": "$TOKEN",
  "title": "$TITLE",
  "body": "$BODY",
  "sound": "default",
  "priority": "high",
  "data": { "taskId": "$TASK_ID", "taskRunId": "$TASK_RUN_ID" }
}
EOF
)"
)

echo "Response: $RESP"

# Pull the receipt id out of {"data":{"id":"…","status":"ok"}}
ID=$(printf '%s' "$RESP" | sed -n 's/.*"id":"\([^"]*\)".*/\1/p')
STATUS=$(printf '%s' "$RESP" | sed -n 's/.*"status":"\([^"]*\)".*/\1/p')

if [[ "$STATUS" != "ok" ]]; then
  echo "Expo refused the push. Status: ${STATUS:-unknown}" >&2
  exit 1
fi

echo "Accepted by Expo (id=$ID). Waiting 3s before checking delivery receipt…"
sleep 3

RECEIPT=$(
  curl -sS \
    -H "Content-Type: application/json" \
    -X POST https://exp.host/--/api/v2/push/getReceipts \
    -d "{\"ids\":[\"$ID\"]}"
)

echo "Receipt: $RECEIPT"

case "$RECEIPT" in
  *'"status":"ok"'*)
    echo "Delivered to APNs/FCM."
    ;;
  *'"status":"error"'*)
    echo "Delivery error — read the message field above (common: DeviceNotRegistered)." >&2
    exit 1
    ;;
  *'{}'*|*'"data":{}'*)
    echo "Receipt not ready yet — re-run the receipt check in a few seconds:"
    echo "  curl -sS -H 'Content-Type: application/json' -X POST https://exp.host/--/api/v2/push/getReceipts -d '{\"ids\":[\"$ID\"]}'"
    ;;
  *)
    echo "Unrecognized receipt shape — check the raw response above." >&2
    ;;
esac
