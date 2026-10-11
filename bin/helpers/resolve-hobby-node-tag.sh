#!/usr/bin/env bash
# Picks the posthog-node image tag that matches the PostHog app image.
#
# The app and Node images come from different workflows. Every master commit gets an
# app image, but a Node image is only built when the commit touches Node code, so the
# Node image that matches app commit X is the newest first-parent ancestor of X that
# has a Node image in the registry. Walking the checkout's history and asking the
# registry about each commit finds it without a copy of the workflow's path filter,
# which would drift. Manifest HEAD requests do not count toward Docker Hub pull limits.
#
# Inputs (environment):
#   REGISTRY_URL      app image repository, e.g. posthog/posthog (default) or
#                     ghcr.io/posthog/posthog. The Node repository is "${REGISTRY_URL}-node",
#                     matching docker-compose.hobby.yml.
#   POSTHOG_APP_TAG   app image tag. A 40-character commit hash starts the walk at that
#                     commit; any other tag starts at HEAD of the checkout.
#   POSTHOG_NODE_TAG  set to pin the Node tag yourself. The script prints it back and
#                     skips the walk.
#   POSTHOG_CHECKOUT  path of the PostHog git checkout (default: posthog).
#   HOBBY_NODE_TAG_MAX_COMMITS  how many commits to walk back (default: 100).
#
# Output: the Node tag on stdout. Exit 0 when the tag is pinned or a matching image was
# found. Exit 1 when none was found; the printed tag is then "latest" and the reason is
# on stderr, so the caller can warn before it starts services.
set -euo pipefail

REGISTRY_URL="${REGISTRY_URL:-posthog/posthog}"
POSTHOG_APP_TAG="${POSTHOG_APP_TAG:?POSTHOG_APP_TAG must be set}"
POSTHOG_CHECKOUT="${POSTHOG_CHECKOUT:-posthog}"
MAX_COMMITS="${HOBBY_NODE_TAG_MAX_COMMITS:-100}"
NODE_REPOSITORY="${REGISTRY_URL}-node"
ACCEPT_MANIFESTS='Accept: application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.docker.distribution.manifest.v2+json'
CURL_TIMEOUTS=(--connect-timeout 10 --max-time 30)

if [ -n "${POSTHOG_NODE_TAG:-}" ]; then
    echo "Using the Node image tag you set: ${NODE_REPOSITORY}:${POSTHOG_NODE_TAG}" >&2
    echo "$POSTHOG_NODE_TAG"
    exit 0
fi

fall_back() {
    cat >&2 <<EOF
No posthog-node image matches the PostHog app image ${REGISTRY_URL}:${POSTHOG_APP_TAG}.
$1
Using ${NODE_REPOSITORY}:latest instead. It may run against a database schema it does not expect.
To use a specific Node image, run the install or upgrade again with POSTHOG_NODE_TAG=<tag> set in your shell.
EOF
    echo "latest"
    exit 1
}

# A repository with no registry host, like posthog/posthog, lives on Docker Hub. Docker
# treats the first path segment as a host only when it has a dot or a port, or is localhost.
first_segment="${REGISTRY_URL%%/*}"
if [[ "$REGISTRY_URL" == */* ]] && { [[ "$first_segment" == *.* ]] || [[ "$first_segment" == *:* ]] || [[ "$first_segment" == localhost ]]; }; then
    registry_host="$first_segment"
    node_repo_path="${REGISTRY_URL#*/}-node"
else
    registry_host="registry-1.docker.io"
    node_repo_path="$NODE_REPOSITORY"
    [[ "$node_repo_path" == */* ]] || node_repo_path="library/$node_repo_path"
fi
scheme="https"
if [[ "$registry_host" == localhost* ]] || [[ "$registry_host" == 127.0.0.1* ]]; then
    scheme="http"
fi
registry_base="${scheme}://${registry_host}"

if [[ "$POSTHOG_APP_TAG" =~ ^[0-9a-f]{40}$ ]]; then
    walk_start="$POSTHOG_APP_TAG"
else
    walk_start="HEAD"
fi
if ! commits=$(git -C "$POSTHOG_CHECKOUT" rev-list --first-parent --max-count="$MAX_COMMITS" "$walk_start" 2>/dev/null) || [ -z "$commits" ]; then
    fall_back "Could not read the commit history for ${walk_start} in ${POSTHOG_CHECKOUT}."
fi
start_commit="${commits%%$'\n'*}"

# The registry answers /v2/ with 401 and a WWW-Authenticate header naming the token
# endpoint when it wants a bearer token. Docker Hub and ghcr.io both issue anonymous
# pull tokens this way. A registry that answers 200 needs no token.
if ! probe_headers=$(curl -sS -o /dev/null -D - "${CURL_TIMEOUTS[@]}" "${registry_base}/v2/" 2>&1); then
    fall_back "Could not reach the registry at ${registry_host}: ${probe_headers}"
fi
auth_args=()
auth_header=$(printf '%s' "$probe_headers" | tr -d '\r' | grep -i '^www-authenticate:' | head -1 || true)
realm=$(printf '%s' "$auth_header" | sed -n 's/.*realm="\([^"]*\)".*/\1/p')
service=$(printf '%s' "$auth_header" | sed -n 's/.*service="\([^"]*\)".*/\1/p')
if [ -n "$realm" ]; then
    token_response=$(curl -sS "${CURL_TIMEOUTS[@]}" "${realm}?service=${service}&scope=repository:${node_repo_path}:pull" || true)
    token=$(printf '%s' "$token_response" | sed -n 's/.*"token" *: *"\([^"]*\)".*/\1/p')
    if [ -z "$token" ]; then
        token=$(printf '%s' "$token_response" | sed -n 's/.*"access_token" *: *"\([^"]*\)".*/\1/p')
    fi
    if [ -z "$token" ]; then
        fall_back "The registry at ${registry_host} did not issue a pull token for ${node_repo_path}."
    fi
    auth_args=(-H "Authorization: Bearer ${token}")
fi

checked=0
for commit in $commits; do
    checked=$((checked + 1))
    status=$(curl -s -o /dev/null -w '%{http_code}' -I "${CURL_TIMEOUTS[@]}" ${auth_args[@]+"${auth_args[@]}"} -H "$ACCEPT_MANIFESTS" "${registry_base}/v2/${node_repo_path}/manifests/${commit}" || true)
    case "$status" in
        200)
            echo "Found ${NODE_REPOSITORY}:${commit:0:10}" >&2
            echo "$commit"
            exit 0
            ;;
        404) ;;
        *)
            fall_back "The registry at ${registry_host} answered ${status} while checking ${node_repo_path}:${commit:0:10}."
            ;;
    esac
done
fall_back "Checked the ${checked} commits from ${start_commit:0:10} back and found no Node image for any of them in ${registry_host}/${node_repo_path}."
