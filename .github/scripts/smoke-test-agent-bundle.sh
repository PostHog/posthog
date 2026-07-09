#!/usr/bin/env bash
#
# Smoke-test one entrypoint inside the posthog-agents image. Runs the bundle
# briefly with fake-but-valid env so config parsing succeeds, then expects
# the service to either reach an I/O dial-out (fine — bundle loaded) or
# exit on a known boot-time validation error (also fine).
#
# Fails the run when the bundle has a load-time problem (missing module,
# syntax error, wrong path in the build output, native-dep crash) — that's
# the failure mode local TS dev does NOT catch but the production bundle
# does, and the whole reason this script exists.
#
# Usage: smoke-test-agent-bundle.sh <image-ref> <entrypoint>
#   <image-ref>   — fully qualified image, e.g.
#                   795637471508.dkr.ecr.us-east-1.amazonaws.com/posthog-agents@sha256:...
#   <entrypoint>  — bundle basename without .mjs (ingress, runner, janitor, migrate)

set -euo pipefail

IMAGE_REF="${1:?image-ref required}"
ENTRYPOINT="${2:?entrypoint required}"

LOG=$(mktemp)
trap 'rm -f "$LOG"' EXIT

# The janitor compiles custom tool sources at runtime through esbuild's JS
# API, which must stay external in the bundle — the API throws "The esbuild
# JavaScript API cannot be bundled" when inlined, and booting the service
# doesn't exercise it, so a bundling regression would otherwise only surface
# on the first PUT /tools/:id in prod. Assert both halves of the contract
# inside the image: the bundle didn't inline the API, and `require('esbuild')`
# resolves from the bundle's location and can actually transform.
if [ "$ENTRYPOINT" = "janitor" ]; then
    docker run --rm --network=none --entrypoint node "$IMAGE_REF" --input-type=module -e '
        import { readFileSync } from "fs"
        import { createRequire } from "module"
        const bundlePath = "/code/products/agent_platform/services/agents/dist/janitor.mjs"
        if (readFileSync(bundlePath, "utf8").includes("esbuild JavaScript API cannot be bundled")) {
            throw new Error("janitor bundle inlined the esbuild JS API — keep esbuild in external in scripts/build.ts")
        }
        const { transform } = createRequire("file://" + bundlePath)("esbuild")
        const out = await transform("const x: number = 1", { loader: "ts" })
        if (!out.code.includes("x = 1")) {
            throw new Error("esbuild transform returned unexpected output: " + out.code)
        }
    '
    echo "✓ janitor keeps esbuild external and can transform TS at runtime"
fi

# `--network=none` keeps the container from accidentally reaching anything real;
# 127.0.0.1:1 is unreachable inside that namespace so connect attempts fail fast
# with ECONNREFUSED / ENETUNREACH — the exact signal we want.
docker run --rm \
    --network=none \
    -e POSTHOG_DB_URL='postgres://x:x@127.0.0.1:1/x' \
    -e AGENT_DB_URL='postgres://x:x@127.0.0.1:1/x' \
    -e AGENT_BUNDLE_S3_BUCKET='smoke-test-bucket' \
    -e AGENT_BUNDLE_S3_ENDPOINT='http://127.0.0.1:1' \
    -e AGENT_BUNDLE_S3_ACCESS_KEY_ID='smoke' \
    -e AGENT_BUNDLE_S3_SECRET_ACCESS_KEY='smoke' \
    -e AGENT_MEMORY_S3_BUCKET='smoke-test-bucket' \
    -e AGENT_MEMORY_S3_ENDPOINT='http://127.0.0.1:1' \
    -e AGENT_MEMORY_S3_ACCESS_KEY_ID='smoke' \
    -e AGENT_MEMORY_S3_SECRET_ACCESS_KEY='smoke' \
    -e ENCRYPTION_SALT_KEYS='00beef0000beef0000beef0000beef00' \
    -e INTERNAL_SECRET='smoke-test-internal-secret' \
    -e AGENT_INTERNAL_SIGNING_KEY='smoke-test-signing-key' \
    -e KAFKA_HOSTS='127.0.0.1:1' \
    -e REDIS_URL='redis://127.0.0.1:1' \
    -e SANDBOX_BACKEND='modal' \
    -e MODAL_TOKEN_ID='smoke-modal-token-id' \
    -e MODAL_TOKEN_SECRET='smoke-modal-token-secret' \
    -e AGENT_USE_AI_GATEWAY='1' \
    -e POSTHOG_AI_GATEWAY_KEY='phs_smoke-test-gateway-key' \
    -e POSTHOG_AI_GATEWAY_URL='http://127.0.0.1:1/v1' \
    -e POSTHOG_API_BASE_URL='http://127.0.0.1:1' \
    -e HTTPS_PROXY='http://127.0.0.1:1' \
    -e NODE_ENV='production' \
    --entrypoint sh \
    "$IMAGE_REF" \
    -c "timeout 5 node products/agent_platform/services/agents/dist/${ENTRYPOINT}.mjs; exit 0" 2>&1 | tee "$LOG" || true

# Bundle-load failures: build is busted. Fail loud.
if grep -qE 'Cannot find (module|package)|SyntaxError|ReferenceError|TypeError: .* is not a function' "$LOG"; then
    echo "::error::${ENTRYPOINT} bundle has a load-time error — see logs above"
    exit 1
fi

# Bundle loaded fine if we see ANY of:
#   - the service announced it bound an HTTP port (`"msg":"listening"`) — ingress
#     and janitor get here without dialling out because they're lazy-connect
#   - a network dial-out failure (the service got past config + tried to talk to PG/S3/Kafka) —
#     runner / migrate hit this because they open pools / S3 at boot
#   - a config-validation throw from zod (config schema rejected our fake values — fine, bundle loaded)
#   - a clean shutdown after `timeout 5` (rare — most services keep retrying connections)
if grep -qE '"msg":"listening"|ECONNREFUSED|ETIMEDOUT|ENOTFOUND|ENETUNREACH|getaddrinfo|timed out|invalid_string|invalid_type|ZodError|connection|fetch failed' "$LOG"; then
    echo "✓ ${ENTRYPOINT} bundle loads and reaches the network/I-O stage"
    exit 0
fi

# Empty / immediate-exit logs are the suspicious case: bundle either died
# silently or never got far enough to log anything. Treat as failure.
echo "::error::${ENTRYPOINT} produced no recognisable boot output — see logs above"
exit 1
