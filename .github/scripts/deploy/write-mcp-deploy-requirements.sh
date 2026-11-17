#!/usr/bin/env bash
# Writes the deploy requirements manifest of the MCP server image (tools/deploy-requirements,
# version 1) with one `django_deploy` requirement for the commit of the image.
#
# The MCP server calls Django endpoints and checks Django scopes, from generated and hand-written
# code. A change that MCP needs from Django lands in the same commit or in an earlier one, because
# master is linear. So a Django build that contains the commit of the image has every such change.
#
# Usage: write-mcp-deploy-requirements.sh OUTPUT_FILE
# Environment: COMMIT_SHA, the full SHA of the commit that the image is built from.
set -euo pipefail

COMMIT_SHA="${COMMIT_SHA:?}"
OUTPUT="${1:?Usage: $0 OUTPUT_FILE}"

if [[ ! "$COMMIT_SHA" =~ ^[0-9a-f]{40}$ ]]; then
    echo "::error::COMMIT_SHA must be a full commit SHA, got '$COMMIT_SHA'." >&2
    exit 1
fi

# Compact JSON with the key order of the schema, because the contract computes the digest over the
# compact requirements list.
requirements=$(jq -nc --arg commit "$COMMIT_SHA" '[{kind: "django_deploy", commit: $commit}]')
if command -v sha256sum >/dev/null; then
    digest=$(printf '%s' "$requirements" | sha256sum | cut -c1-12)
else
    digest=$(printf '%s' "$requirements" | shasum -a 256 | cut -c1-12)
fi
jq -nc --arg source "$COMMIT_SHA" --arg digest "$digest" --argjson requirements "$requirements" \
    '{schema_version: 1, source_commit: $source, digest: $digest, requirements: $requirements}' >"$OUTPUT"
