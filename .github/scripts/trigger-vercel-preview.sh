#!/bin/bash
set -e

# Trigger Vercel preview build via API
# Args: $1 = PR branch name or ref name

if [ -z "$VERCEL_TOKEN" ] || [ -z "$VERCEL_TEAM_ID" ] || [ -z "$VERCEL_PROJECT_ID" ]; then
  echo "⚠️ Vercel secrets not configured, skipping"
  exit 0
fi

PR_BRANCH="$1"

echo "📢 Triggering Vercel deployment for posthog.com@master (gatsby-source-git)"
echo "   Monorepo branch: $PR_BRANCH (per-deployment env)"

PAYLOAD='{
  "name": "posthog-com",
  "project": "'"$VERCEL_PROJECT_ID"'",
  "gitSource": {
    "type": "github",
    "repoId": "260550412",
    "ref": "master"
  },
  "build": {
    "env": {
      "GATSBY_POSTHOG_BRANCH": "'"$PR_BRANCH"'"
    }
  }
}'

RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "https://api.vercel.com/v13/deployments?teamId=${VERCEL_TEAM_ID}" \
  -H "Authorization: Bearer $VERCEL_TOKEN" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD")

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | head -n-1)

if [ "$HTTP_CODE" -eq 200 ] || [ "$HTTP_CODE" -eq 201 ]; then
  DEPLOYMENT_URL=$(echo "$BODY" | jq -r '.url // empty')
  DEPLOYMENT_ID=$(echo "$BODY" | jq -r '.id // empty')
  echo "✅ Successfully triggered Vercel preview build"
  echo "trigger_status=success" >> "$GITHUB_OUTPUT"
  if [ -n "$DEPLOYMENT_URL" ]; then
    echo "   Preview URL: https://${DEPLOYMENT_URL}"
    echo "deployment_url=https://${DEPLOYMENT_URL}" >> "$GITHUB_OUTPUT"
  fi
  if [ -n "$DEPLOYMENT_ID" ]; then
    echo "deployment_id=${DEPLOYMENT_ID}" >> "$GITHUB_OUTPUT"
  fi
else
  echo "❌ Failed to trigger preview build (HTTP $HTTP_CODE)"
  echo "$BODY" | jq '.' 2>/dev/null || echo "$BODY"
  echo "trigger_status=failed" >> "$GITHUB_OUTPUT"
fi
