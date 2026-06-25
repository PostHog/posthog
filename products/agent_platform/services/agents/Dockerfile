# PostHog agent-platform runtime image.
#
# Single image, three entrypoints: ingress, runner, janitor.
# The deploy manifest picks which one runs in each replica / Job:
#
#   command: ["node", "products/agent_platform/services/agents/dist/ingress.mjs"]
#   command: ["node", "products/agent_platform/services/agents/dist/runner.mjs"]
#   command: ["node", "products/agent_platform/services/agents/dist/janitor.mjs"]
#
# Schema is Django-owned (the `agent_platform` product DB), migrated by the
# posthog-django `migrate_product_databases` job — no node migrate entrypoint.
#
# Runtime WORKDIR is `/code`; bundles live at
# `/code/products/agent_platform/services/agents/dist/` so Node module
# resolution walks up to `products/agent_platform/services/agents/node_modules/`
# (where pnpm symlinks node-rdkafka) and then to `/code/node_modules/.pnpm/`
# (the actual content). See the COPY block below for the layout.
#
# Build from repo root so pnpm can resolve the workspace:
#
#   docker build -f products/agent_platform/services/agents/Dockerfile -t posthog-agents .
#
# Reference: services/mcp/Dockerfile (same bundling strategy — esbuild
# emits self-contained .mjs, runtime has no node_modules).

# Pinned to .nvmrc (24.13.0). The three runtime services declare
# `engines.node: ">=24 <25"` and import top-level await.
ARG NODE_VERSION=24.13.0
ARG NODE_IMAGE=node:${NODE_VERSION}-bookworm-slim

#
# Build stage — workspace install + esbuild bundling.
#
FROM ${NODE_IMAGE} AS build
WORKDIR /code
SHELL ["/bin/bash", "-e", "-o", "pipefail", "-c"]

# Build toolchain for `node-rdkafka`'s gyp + Confluent's librdkafka 2.10.1.
# Same package pins as Dockerfile.node so the agent stack stays on the
# same librdkafka as the rest of the PostHog node fleet (the runner can
# load KafkaLogSink the moment `KAFKA_BROKERS` is set — no rebuild).
# `BUILD_LIBRDKAFKA=0` tells node-rdkafka to skip its bundled build and
# link against the system one we just installed.
RUN apt-get update && \
    apt-get install -y --no-install-recommends wget gnupg ca-certificates && \
    mkdir -p /etc/apt/keyrings && \
    wget -qO - https://packages.confluent.io/clients/deb/archive.key | \
        gpg --dearmor -o /etc/apt/keyrings/confluent-clients.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/confluent-clients.gpg] https://packages.confluent.io/clients/deb/ bookworm main" \
        > /etc/apt/sources.list.d/confluent-clients.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends --allow-downgrades \
        make g++ gcc python3 \
        "librdkafka1=2.10.1-1.cflt~deb12" \
        "librdkafka++1=2.10.1-1.cflt~deb12" \
        "librdkafka-dev=2.10.1-1.cflt~deb12" && \
    rm -rf /var/lib/apt/lists/*
ENV BUILD_LIBRDKAFKA=0

# `corepack enable` picks the pnpm version from `packageManager` in the
# root package.json. No `corepack prepare` — non-deterministic.
RUN corepack enable

# Manifests + lockfile first so the install layer caches across unrelated
# source edits. `patches/` is referenced from pnpm-lock.yaml.
COPY pnpm-lock.yaml pnpm-workspace.yaml package.json tsconfig.json ./
COPY patches/ patches/

# pnpm reads every referenced workspace package.json BEFORE install to
# build the dep graph. Copy manifests separately from sources so source
# edits don't bust the install cache.
COPY products/agent_platform/services/agents/package.json products/agent_platform/services/agents/package.json
COPY products/agent_platform/services/agent-ingress/package.json products/agent_platform/services/agent-ingress/package.json
COPY products/agent_platform/services/agent-runner/package.json products/agent_platform/services/agent-runner/package.json
COPY products/agent_platform/services/agent-janitor/package.json products/agent_platform/services/agent-janitor/package.json
COPY products/agent_platform/services/agent-shared/package.json products/agent_platform/services/agent-shared/package.json
COPY products/agent_platform/services/agent-tools/package.json products/agent_platform/services/agent-tools/package.json

# Full install (no --ignore-scripts) so node-rdkafka's gyp build runs
# against the librdkafka we installed above. Without this, KafkaLogSink
# would fail at `await import('node-rdkafka')` the first time anyone
# sets `KAFKA_BROKERS` — the image would look healthy but silently lose
# the prod Kafka path. `pg-native` is marked external in the esbuild
# config (none of the services call `pg.native`).
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile \
        --filter '@posthog/agents-image...' \
        --filter '@posthog/agent-ingress...' \
        --filter '@posthog/agent-runner...' \
        --filter '@posthog/agent-janitor...'

# Sources. Ordered shared-first so a change to (say) ingress doesn't
# invalidate the shared layer.
COPY products/agent_platform/services/agent-shared/ products/agent_platform/services/agent-shared/
COPY products/agent_platform/services/agent-tools/ products/agent_platform/services/agent-tools/
COPY products/agent_platform/services/agent-ingress/ products/agent_platform/services/agent-ingress/
COPY products/agent_platform/services/agent-runner/ products/agent_platform/services/agent-runner/
COPY products/agent_platform/services/agent-janitor/ products/agent_platform/services/agent-janitor/
COPY products/agent_platform/services/agents/ products/agent_platform/services/agents/

WORKDIR /code/products/agent_platform/services/agents
RUN pnpm run build

#
# Runtime stage — slim image with bundles + migration SQL + the one
# native dep (node-rdkafka) we left external in esbuild.
#
FROM ${NODE_IMAGE}
WORKDIR /code
SHELL ["/bin/bash", "-e", "-o", "pipefail", "-c"]

# Runtime librdkafka 2.10.1 (matches Dockerfile.node). Only the runtime
# libs, not the dev headers — keeps the image lean.
RUN apt-get update && \
    apt-get install -y --no-install-recommends wget gnupg ca-certificates && \
    mkdir -p /etc/apt/keyrings && \
    wget -qO - https://packages.confluent.io/clients/deb/archive.key | \
        gpg --dearmor -o /etc/apt/keyrings/confluent-clients.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/confluent-clients.gpg] https://packages.confluent.io/clients/deb/ bookworm main" \
        > /etc/apt/sources.list.d/confluent-clients.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends --allow-downgrades \
        "librdkafka1=2.10.1-1.cflt~deb12" \
        "librdkafka++1=2.10.1-1.cflt~deb12" && \
    apt-get purge -y wget gnupg && apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# Commit hash for incident triage. Matches the convention in
# Dockerfile.node and services/mcp/Dockerfile.
ARG COMMIT_HASH
RUN echo "${COMMIT_HASH:-unknown}" > /code/commit.txt

# Keep the bundles inside `products/agent_platform/services/agents/` so Node's
# module resolution walks up to
# `products/agent_platform/services/agents/node_modules/` (where pnpm symlinks
# `node-rdkafka` because @posthog/agents-image declares it as a direct dep) and
# then to `/code/node_modules/.pnpm/...` (the actual content). The in-image path
# mirrors the build-stage path so the pnpm symlink farm stays valid.
COPY --from=build --chown=node:node /code/products/agent_platform/services/agents/dist/ ./products/agent_platform/services/agents/dist/

# Workspace symlinks for the bundle's externals.
# `products/agent_platform/services/agents/node_modules/` is a pnpm symlink
# farm; the underlying `.pnpm` store at the workspace root holds the real
# content (notably node-rdkafka's compiled .node addon). Both have to be
# carried over at the same paths they had in the build stage.
COPY --from=build --chown=node:node /code/products/agent_platform/services/agents/node_modules/ /code/products/agent_platform/services/agents/node_modules/
COPY --from=build --chown=node:node /code/node_modules/.pnpm/ /code/node_modules/.pnpm/

ENV NODE_ENV=production

# 8080 = ingress default, 8082 = janitor default. The runner and the
# migration Job don't listen on a port. EXPOSE is documentation only —
# k8s ignores it; the deploy manifest sets containerPort per release.
EXPOSE 8080 8082

USER node

# No default CMD on purpose — every deploy must declare which entrypoint
# it runs. Locally: `docker run posthog-agents node dist/runner.mjs`.
