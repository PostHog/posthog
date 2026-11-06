#
# Dockerfile.node - nodejs Only
#
# This Dockerfile builds only the nodejs (Node.js app) without Django, frontend, or other PostHog components.
# Use this for running standalone Node.js plugin server instances.
#

#
# Build stage: Compile nodejs and dependencies
#
FROM ghcr.io/posthog/rust-node-container:bookworm_rust_1.91-node_26.13.0 AS build

# Compile and install system dependencies
# Add Confluent's client repository for librdkafka 2.12.0
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    "wget" \
    "gnupg" \
    && \
    mkdir -p /etc/apt/keyrings && \
    wget -qO - https://packages.confluent.io/clients/deb/archive.key | gpg --dearmor -o /etc/apt/keyrings/confluent-clients.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/confluent-clients.gpg] https://packages.confluent.io/clients/deb/ bookworm main" > /etc/apt/sources.list.d/confluent-clients.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends --allow-downgrades \
    "make" \
    "g++" \
    "gcc" \
    "python3" \
    "librdkafka1=2.12.0-1.cflt~deb12" \
    "librdkafka++1=2.12.0-1.cflt~deb12" \
    "librdkafka-dev=2.12.0-1.cflt~deb12" \
    # libssl pinned to the 3.0 series (ABI-stable), not an exact version: Debian rotates
    # point releases out of the security archive, which breaks exact pins on uncached builds.
    "libssl-dev=3.0.*" \
    "libssl3=3.0.*" \
    "zlib1g-dev" \
    && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /code
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .nvmrc ./
COPY packages/common/package.json ./packages/common/
COPY packages/ingestion/package.json ./packages/ingestion/
SHELL ["/bin/bash", "-e", "-o", "pipefail", "-c"]

# Use system librdkafka from Confluent instead of the bundled version
ENV BUILD_LIBRDKAFKA=0

RUN rm -rf /usr/local/bin/yarn /usr/local/bin/yarnpkg /opt/yarn-v* && \
    npm install -g corepack@0.36.0
RUN --mount=type=cache,id=pnpm,target=/tmp/pnpm-store-v24 \
    corepack enable && \
    NODE_OPTIONS="--max-old-space-size=16384" CI=1 pnpm install --frozen-lockfile --store-dir /tmp/pnpm-store-v24

COPY packages/common/ ./packages/common/
COPY packages/ingestion/ ./packages/ingestion/
RUN NODE_OPTIONS="--max-old-space-size=16384" pnpm --dir packages/common build && \
    NODE_OPTIONS="--max-old-space-size=16384" pnpm --dir packages/ingestion build

#
# Runtime stage: Minimal image with only nodejs runtime dependencies
#
# Trixie, not bookworm: the uWebSockets.js binary for Node 26 needs glibc 2.38, and bookworm ships 2.36.
FROM node:26.13.0-trixie-slim
WORKDIR /code
SHELL ["/bin/bash", "-e", "-o", "pipefail", "-c"]

# Install runtime dependencies
# Add Confluent's client repository for librdkafka runtime
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    "ca-certificates" \
    "wget" \
    "gnupg" \
    && \
    mkdir -p /etc/apt/keyrings && \
    wget -qO - https://packages.confluent.io/clients/deb/archive.key | gpg --dearmor -o /etc/apt/keyrings/confluent-clients.gpg && \
    # The bookworm repo, because Confluent publishes no 2.12.0 build for trixie. The runtime
    # librdkafka must match the 2.12.0 headers that the build stage compiles node-rdkafka against.
    echo "deb [signed-by=/etc/apt/keyrings/confluent-clients.gpg] https://packages.confluent.io/clients/deb/ bookworm main" > /etc/apt/sources.list.d/confluent-clients.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends --allow-downgrades \
    "librdkafka1=2.12.0-1.cflt~deb12" \
    "librdkafka++1=2.12.0-1.cflt~deb12" \
    # libssl pinned to the 3.5 series (ABI-stable), not an exact version: Debian rotates
    # point releases out of the security archive, which breaks exact pins on uncached builds.
    "libssl3t64=3.5.*" \
    "curl" \
    "gettext-base" \
    "libjemalloc2" \
    && \
    rm -rf /var/lib/apt/lists/*
# curl: Required by bin/nodejs startup script to fetch EC2 metadata when INJECT_EC2_CLIENT_RACK is set
# gettext-base: Provides envsubst command used by bin/nodejs to substitute environment variables in Kafka client IDs

# Install and use a non-root user
RUN groupadd -g 10001 posthog && \
    useradd -u 10001 -g posthog -m -d /home/posthog posthog && \
    chown -R posthog:posthog /code


# Add in the compiled nodejs & its runtime dependencies from the build stage
COPY --from=build --chown=posthog:posthog /code/node_modules /code/node_modules
COPY --from=build --chown=posthog:posthog /code/package.json /code/package.json
COPY --from=build --chown=posthog:posthog /code/packages/common/dist /code/packages/common/dist
COPY --from=build --chown=posthog:posthog /code/packages/common/node_modules /code/packages/common/node_modules
COPY --from=build --chown=posthog:posthog /code/packages/common/package.json /code/packages/common/package.json
COPY --from=build --chown=posthog:posthog /code/packages/ingestion/dist /code/packages/ingestion/dist
COPY --from=build --chown=posthog:posthog /code/packages/ingestion/node_modules /code/packages/ingestion/node_modules
COPY --from=build --chown=posthog:posthog /code/packages/ingestion/package.json /code/packages/ingestion/package.json

USER posthog

ARG COMMIT_HASH
RUN echo ${COMMIT_HASH:-unknown} > /code/commit.txt

ENV NODE_ENV=production
CMD ["node", "packages/ingestion/dist/index.js"]
