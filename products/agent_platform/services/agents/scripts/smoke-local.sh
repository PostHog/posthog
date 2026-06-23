#!/usr/bin/env bash
# Build the posthog-agents container image locally and smoke-test all four
# bundled entrypoints against it. Same script CI uses for the production
# image (`.github/scripts/smoke-test-agent-bundle.sh`); this wrapper just
# handles the local build + per-entrypoint loop.
#
# Usage:
#   services/agents/scripts/smoke-local.sh                  # build + smoke all 4
#   services/agents/scripts/smoke-local.sh ingress runner   # build + smoke a subset
#   SKIP_BUILD=1 services/agents/scripts/smoke-local.sh     # smoke against existing posthog-agents:dev tag
#   IMAGE=ghcr.io/.../...@sha256:...  services/agents/scripts/smoke-local.sh   # smoke a specific reference
#
# What "passes" means: each entrypoint boots, loads its bundle cleanly, and
# either reaches the network dial-out stage (PG/S3/Kafka/etc, expected to
# fail because --network=none) or binds an HTTP listener. Catches the
# "bundle has a missing import / wrong path / native-dep crash" class of bug
# that local `tsx src/index.ts` misses because esbuild reorganises module
# resolution at build time.

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/../../../../.." && pwd)"
SMOKE_SCRIPT="$REPO_ROOT/.github/scripts/smoke-test-agent-bundle.sh"

IMAGE="${IMAGE:-posthog-agents:dev}"
SKIP_BUILD="${SKIP_BUILD:-0}"

if [ ! -x "$SMOKE_SCRIPT" ]; then
    echo "error: smoke script not found at $SMOKE_SCRIPT" >&2
    exit 1
fi

ENTRYPOINTS=("$@")
if [ "${#ENTRYPOINTS[@]}" -eq 0 ]; then
    ENTRYPOINTS=(ingress runner janitor migrate)
fi

if [ "$SKIP_BUILD" = "0" ] && [ -z "${IMAGE_OVERRIDE:-}" ] && [ "$IMAGE" = "posthog-agents:dev" ]; then
    echo "::group::Build $IMAGE (set SKIP_BUILD=1 to reuse existing tag)"
    docker build \
        -f "$REPO_ROOT/products/agent_platform/services/agents/Dockerfile" \
        -t "$IMAGE" \
        "$REPO_ROOT"
    echo "::endgroup::"
else
    echo "Using existing image: $IMAGE (skipping build)"
fi

fail=0
for entrypoint in "${ENTRYPOINTS[@]}"; do
    echo "::group::Smoke $entrypoint"
    if "$SMOKE_SCRIPT" "$IMAGE" "$entrypoint"; then
        echo "✓ $entrypoint"
    else
        echo "✗ $entrypoint" >&2
        fail=1
    fi
    echo "::endgroup::"
done

if [ "$fail" -ne 0 ]; then
    echo "smoke-local: one or more entrypoints failed — see logs above" >&2
    exit 1
fi
echo "smoke-local: all entrypoints OK"
