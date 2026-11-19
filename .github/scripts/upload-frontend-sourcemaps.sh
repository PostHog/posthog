#!/usr/bin/env bash
# Uploads the sourcemaps of an exported frontend build to error tracking, and turns the export into the
# `sourcemap-upload` stage of the Dockerfile, which the image build then takes as a build context.
#
# Usage: upload-frontend-sourcemaps.sh <hog> <export dir> <release version>
#
# The export dir holds code/frontend/dist, as the `frontend-dist` stage writes it. Afterwards it also
# holds the files the Dockerfile reads from that stage: /tmp/.sourcemaps-status says "uploaded", so the
# image build strips any remaining .map files, and /tmp/.sourcemaps-processed.
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

# Runs outside the checkout, so hog reads no .git and no posthog.json but the one written here.
cd "$out/code"
cat >posthog.json <<EOF
{
    "host": "https://us.posthog.com",
    "projectId": 2,
    "errorTracking": { "sources": [{ "path": "frontend/dist", "ignore": ["**/$STABLE_CHUNKS"] }] }
}
EOF
export HOG_NO_UPDATE_CHECK=1

"$hog" error-tracking process -o text \
    --public-path-prefix /static \
    --release-mode event \
    --release-name posthog \
    --release-version "$version"

# Without GITHUB_SHA hog resolves no release, so it injects only the chunk ID, which it derives from
# the file's own content.
stable=$(find frontend/dist -type f -name "$STABLE_CHUNKS")
if [ -n "$stable" ]; then
    env -u GITHUB_SHA "$hog" error-tracking process - -o text \
        --public-path-prefix /static \
        --release-mode event <<<"$stable"
fi

# The image build strips them anyway once the status says "uploaded". Deleting them here keeps the
# gigabytes of maps out of the build context.
find frontend/dist \( -name '*.map' -o -name '*.map.gz' -o -name '*.map.br' \) -delete
rm posthog.json
mkdir -p "$out/tmp"
echo uploaded >"$out/tmp/.sourcemaps-status"
touch "$out/tmp/.sourcemaps-processed"
