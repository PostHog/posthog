#!/usr/bin/env bash
# Holds a deploy until the `django_deploy` requirements of a deploy requirements manifest
# (tools/deploy-requirements, version 1) are met, with wait-for-backend-deploy.sh.
#
# This reader knows only `django_deploy`. An unknown schema_version or kind is an error, never a
# pass, because a skipped requirement would report a pass for something that nothing checked.
# The manifest comes from the build job of the same run, so a missing file is an error too.
#
# Usage: wait-for-deploy-requirements.sh <manifest file>
# Environment: REPOSITORY, GH_TOKEN, and the TIMEOUT_SECONDS and INTERVAL_SECONDS of the wait.
# Exit codes: those of wait-for-backend-deploy.sh. 0 met, 3 timed out, 1 error.
set -euo pipefail

MANIFEST="${1:?Usage: $0 <manifest file>}"
WAIT_FOR_BACKEND_DEPLOY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/wait-for-backend-deploy.sh"

if [ ! -s "$MANIFEST" ]; then
    echo "::error::The deploy requirements manifest $MANIFEST is missing or empty." >&2
    exit 1
fi
if ! jq -e '
    .schema_version == 1
    and (.requirements | type == "array")
    and all(.requirements[];
        .kind == "django_deploy" and (.commit | type == "string" and test("^[0-9a-f]{40}$")))
    ' "$MANIFEST" >/dev/null 2>&1; then
    echo "::error::$MANIFEST is not a schema_version 1 manifest with only django_deploy requirements." >&2
    exit 1
fi

while read -r commit; do
    [ -n "$commit" ] || continue
    COMMIT_SHA="$commit" "$WAIT_FOR_BACKEND_DEPLOY"
done < <(jq -r '.requirements[].commit' "$MANIFEST")
echo "Every deploy requirement in $MANIFEST is met."
