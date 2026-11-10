#
# One of ingestion's Node service packages, chosen with PACKAGE (the pnpm filter) and PACKAGE_DIR;
# ingestion/ci/images.yml sets them per image. Built from the repository root, like Dockerfile.node,
# because the package and the native addons it uses are members of the root pnpm workspace and the
# rust/ cargo workspace. ingestion/node/Dockerfile.dockerignore limits the context.
#

# Every workspace package the service loads at runtime: its own and its dependencies.
ARG RUNTIME_PACKAGES="common/hogvm/typescript nodejs/packages/hog-engine nodejs/packages/common nodejs/packages/replay-storage ingestion/node/packages/common ingestion/node/packages/ingestion"

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

# An empty build arg (the workflow always passes both) falls back to the ingestion package.
ARG PACKAGE
ARG PACKAGE_DIR
WORKDIR /code
COPY turbo.json package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.json .nvmrc ./
COPY ./bin/turbo ./bin/turbo
COPY ./patches ./patches
# The native addons build from the cargo workspace, which lists ingestion/rust as members.
COPY ./rust ./rust
COPY ./ingestion/rust ./ingestion/rust
COPY ./common/esbuilder/ ./common/esbuilder/
COPY ./common/hogvm/typescript/ ./common/hogvm/typescript/
COPY ./nodejs/packages/hog-engine/ ./nodejs/packages/hog-engine/
COPY ./nodejs/packages/common/ ./nodejs/packages/common/
COPY ./ingestion/node/packages/common/ ./ingestion/node/packages/common/
COPY ./nodejs/packages/replay-storage/ ./nodejs/packages/replay-storage/
COPY ./ingestion/node/packages/ingestion/package.json ./ingestion/node/packages/ingestion/
COPY ./${PACKAGE_DIR:-ingestion/node/packages/ingestion}/package.json ./${PACKAGE_DIR:-ingestion/node/packages/ingestion}/
SHELL ["/bin/bash", "-e", "-o", "pipefail", "-c"]

# Use system librdkafka from Confluent instead of the bundled version
ENV BUILD_LIBRDKAFKA=0

RUN rm -rf /usr/local/bin/yarn /usr/local/bin/yarnpkg /opt/yarn-v* && \
    npm install -g corepack@0.36.0
RUN --mount=type=cache,id=pnpm,target=/tmp/pnpm-store-v24 \
    corepack enable && \
    NODE_OPTIONS="--max-old-space-size=16384" CI=1 pnpm --filter=${PACKAGE:-@posthog/ingestion}... install --frozen-lockfile --store-dir /tmp/pnpm-store-v24

COPY ./ingestion/node/packages/ingestion/ ./ingestion/node/packages/ingestion/
COPY ./${PACKAGE_DIR:-ingestion/node/packages/ingestion}/ ./${PACKAGE_DIR:-ingestion/node/packages/ingestion}/
RUN NODE_OPTIONS="--max-old-space-size=16384" bin/turbo --filter=${PACKAGE:-@posthog/ingestion} build

# Record the Django and sqlx migrations this build reads, so the deploy-time schema check can wait for them
# (nodejs/packages/common/src/schema-check). Bind mounts give the generator the migration files without adding
# the Python trees to any layer, and BuildKit reruns this step when any mounted file changes.
ARG RUNTIME_PACKAGES
ARG COMMIT_HASH
RUN --mount=type=bind,source=posthog,target=/schema-src/posthog \
    --mount=type=bind,source=ee,target=/schema-src/ee \
    --mount=type=bind,source=products,target=/schema-src/products \
    --mount=type=bind,source=common/hogvm/typescript,target=/schema-src/common/hogvm/typescript \
    --mount=type=bind,source=nodejs/packages,target=/schema-src/nodejs/packages \
    --mount=type=bind,source=ingestion/node/packages,target=/schema-src/ingestion/node/packages \
    --mount=type=bind,source=ingestion/rust/persons_migrations,target=/schema-src/rust/persons_migrations \
    --mount=type=bind,source=rust/cyclotron-node-migrations,target=/schema-src/rust/cyclotron-node-migrations \
    --mount=type=bind,source=rust/behavioral_cohorts_migrations,target=/schema-src/rust/behavioral_cohorts_migrations \
    roots=""; for pkg in ${RUNTIME_PACKAGES}; do roots="${roots} --source-root ${pkg}/src"; done && \
    node nodejs/packages/common/dist/schema-check/generate.js \
    --repo-root /schema-src \
    ${roots} \
    --output ingestion/node/schema-requirements.json \
    --source-commit "${COMMIT_HASH:-unknown}"

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
COPY --from=build --chown=posthog:posthog /code/rust/common/hogvm/node/package.json /code/rust/common/hogvm/node/package.json
COPY --from=build --chown=posthog:posthog /code/rust/common/hogvm/node/index.js /code/rust/common/hogvm/node/index.js
COPY --from=build --chown=posthog:posthog /code/rust/common/hogvm/node/index.node /code/rust/common/hogvm/node/index.node
COPY --from=build --chown=posthog:posthog /code/rust/replay-anonymizer-node/dist /code/rust/replay-anonymizer-node/dist
COPY --from=build --chown=posthog:posthog /code/rust/replay-anonymizer-node/package.json /code/rust/replay-anonymizer-node/package.json
COPY --from=build --chown=posthog:posthog /code/rust/replay-anonymizer-node/index.node /code/rust/replay-anonymizer-node/index.node
COPY --from=build --chown=posthog:posthog /code/rust/ai-research/replay-core-v4-node/dist /code/rust/ai-research/replay-core-v4-node/dist
COPY --from=build --chown=posthog:posthog /code/rust/ai-research/replay-core-v4-node/package.json /code/rust/ai-research/replay-core-v4-node/package.json
COPY --from=build --chown=posthog:posthog /code/rust/ai-research/replay-core-v4-node/index.node /code/rust/ai-research/replay-core-v4-node/index.node
ARG PACKAGE_DIR
ARG RUNTIME_PACKAGES
RUN --mount=type=bind,from=build,source=/code,target=/build \
    for pkg in ${RUNTIME_PACKAGES}; do \
        mkdir -p "/code/${pkg}" && cp -r "/build/${pkg}/dist" "/build/${pkg}/node_modules" "/build/${pkg}/package.json" "/code/${pkg}/"; \
    done && chown -R posthog:posthog /code
COPY --from=build --chown=posthog:posthog /code/ingestion/node/schema-requirements.json /code/ingestion/node/schema-requirements.json

USER posthog

ARG COMMIT_HASH
RUN echo ${COMMIT_HASH:-unknown} > /code/commit.txt

ENV NODE_ENV=production
ENV PACKAGE_DIR=${PACKAGE_DIR:-ingestion/node/packages/ingestion}
CMD node "${PACKAGE_DIR}/dist/index.js"
