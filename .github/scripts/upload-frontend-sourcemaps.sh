#!/usr/bin/env bash
# Uploads the sourcemaps of an exported frontend build to error tracking, and turns the export into the
# `sourcemap-upload` stage of the Dockerfile, which the image build then takes as a build context.
#
# Usage: upload-frontend-sourcemaps.sh <hog> <export dir> <release version>
#
# The export dir holds code/frontend/dist, as the `frontend-dist` stage writes it. Afterwards it also
# holds the files the Dockerfile reads from that stage: /tmp/.sourcemaps-status says "uploaded", so the
# image build strips the .map files after collectstatic, and /tmp/.sourcemaps-processed.
#
# The upload runs in the CI job rather than in the image build, so the job's credentials never enter
# a build. Any failure exits non-zero, and the workflow then builds the image without this context,
# which keeps the .map files in the image.
set -euo pipefail

hog=$1
out=$2
version=$3

# The stable-name copies (`*-S<10 hex>.js`, see frontend/bin/stableChunkNames.mjs) keep one URL for as
# long as their code is unchanged, so they must not carry the per-release ID the first pass injects.
readonly STABLE_CHUNKS='*-S[0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F].js'

# Runs outside the checkout, so hog reads no .git and no posthog.json but the one written here, which
# takes the host and project from the repository's posthog.json.
config="$(cd "${GITHUB_WORKSPACE:-.}" && pwd)/posthog.json"
cd "$out/code"
jq --arg ignore "**/$STABLE_CHUNKS" \
    '{host, projectId, errorTracking: {sources: [{path: "frontend/dist", ignore: [$ignore]}]}}' \
    "$config" >posthog.json
export HOG_NO_UPDATE_CHECK=1

# Fails the script unless every symbol set reached PostHog and hog skipped no file, so the maps are
# deleted only when error tracking holds each of them. hog exits 0 after skipping a map that is too
# large or unreadable.
check() {
    local result
    result=$(cat)
    jq -c '{release, symbolSets: (.symbolSets | group_by(.status) | map({key: .[0].status, value: length}) | from_entries), skipped}' <<<"$result"
    jq -e '(.skipped | length == 0) and all(.symbolSets[]; .status == "uploaded" or .status == "already_present")' \
        <<<"$result" >/dev/null
}

"$hog" error-tracking process -o json \
    --public-path-prefix /static \
    --release-mode event \
    --release-name posthog \
    --release-version "$version" | check

# Without GITHUB_SHA hog resolves no release, so it injects only the chunk ID, which it derives from
# the file's own content. A stable copy without a map has nothing to upload, so it is left out.
stable=$(find frontend/dist -type f -name "$STABLE_CHUNKS" -exec grep -l 'sourceMappingURL=' {} + || true)
if [ -n "$stable" ]; then
    env -u GITHUB_SHA "$hog" error-tracking process - -o json \
        --public-path-prefix /static \
        --release-mode event <<<"$stable" | check
fi

# The .map files stay: collectstatic resolves each bundle's sourceMappingURL and fails on a missing
# map, so the image build strips them only after it.
rm posthog.json
mkdir -p "$out/tmp"
echo uploaded >"$out/tmp/.sourcemaps-status"
touch "$out/tmp/.sourcemaps-processed"
