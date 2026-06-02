#!/usr/bin/env bash
#
# Smoke-test the posthog-agent-console image. The Next.js standalone server
# starts a real HTTP listener; we let it boot, poll /api/healthz, and tear
# it back down. A boot crash is the failure mode local dev doesn't catch
# but the production bundle does (output: 'standalone' produces a different
# Node graph than `next dev`).
#
# Usage: smoke-test-agent-console.sh <image-ref>

set -euo pipefail

IMAGE_REF="${1:?image-ref required}"

CID=$(docker run --rm -d \
    -p 3040:3040 \
    -e NODE_ENV='production' \
    "$IMAGE_REF")

cleanup() {
    docker logs "$CID" 2>&1 | tail -100 || true
    docker kill "$CID" 2>/dev/null || true
}
trap cleanup EXIT

# Give Next.js a moment to bind. Standalone boot is usually sub-second; cap
# at 30s and poll so a slow startup doesn't yield a spurious fail.
for _ in $(seq 1 30); do
    if curl --silent --fail --max-time 1 http://127.0.0.1:3040/api/healthz > /dev/null; then
        echo "✓ agent-console responds 200 on /api/healthz"
        exit 0
    fi
    # Bail early if the container already crashed.
    if ! docker inspect -f '{{.State.Running}}' "$CID" 2>/dev/null | grep -q true; then
        echo "::error::agent-console container exited before responding to healthz"
        exit 1
    fi
    sleep 1
done

echo "::error::agent-console did not respond to /api/healthz within 30s"
exit 1
