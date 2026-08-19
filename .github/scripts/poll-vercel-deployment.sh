#!/bin/bash
set -e

# Poll a Vercel deployment until it reaches a terminal state.
# Args: $1 = deployment id
# Emits deployment_state to GITHUB_OUTPUT: READY, ERROR, CANCELED, or UNKNOWN.

if [ -z "$VERCEL_TOKEN" ] || [ -z "$VERCEL_TEAM_ID" ]; then
  echo "⚠️ Vercel secrets not configured, skipping"
  exit 0
fi

DEPLOYMENT_ID="$1"

if [ -z "$DEPLOYMENT_ID" ]; then
  echo "⚠️ No deployment id supplied, skipping poll"
  echo "deployment_state=UNKNOWN" >> "$GITHUB_OUTPUT"
  exit 0
fi

# The build takes about 10 minutes, so poll long enough to see it finish or get cancelled.
MAX_WAIT_SECONDS="${MAX_WAIT_SECONDS:-780}"
POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-15}"

elapsed=0
state="UNKNOWN"

while [ "$elapsed" -lt "$MAX_WAIT_SECONDS" ]; do
  RESPONSE=$(curl -s "https://api.vercel.com/v13/deployments/${DEPLOYMENT_ID}?teamId=${VERCEL_TEAM_ID}" \
    -H "Authorization: Bearer $VERCEL_TOKEN")
  state=$(echo "$RESPONSE" | jq -r '.readyState // .status // "UNKNOWN"')
  echo "   Deployment state: $state (${elapsed}s elapsed)"

  case "$state" in
    READY | ERROR | CANCELED)
      break
      ;;
  esac

  sleep "$POLL_INTERVAL_SECONDS"
  elapsed=$((elapsed + POLL_INTERVAL_SECONDS))
done

echo "deployment_state=${state}" >> "$GITHUB_OUTPUT"

if [ "$state" = "READY" ]; then
  echo "✅ Deployment ready"
elif [ "$state" = "ERROR" ] || [ "$state" = "CANCELED" ]; then
  echo "❌ Deployment ended in state: $state"
else
  echo "⏱️ Deployment still in progress after ${MAX_WAIT_SECONDS}s (state: $state)"
fi
