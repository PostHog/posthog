#
# Dockerfile for production build of the plugin server. We first bundle the
# dependencies and build the TypeScript code, then copy the artifacts to the
# final image.
#

FROM node:18.12.1-bullseye-slim AS plugin-server-build
WORKDIR /code/plugin-server
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Compile and install Node.js dependencies.
COPY ./package.json ./pnpm-lock.yaml ./tsconfig.json ./
COPY ./patches/ ./patches/
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    "make" \
    "g++" \
    "gcc" \
    "python3" \
    "libssl-dev" \
    "zlib1g-dev" \
    && \
    rm -rf /var/lib/apt/lists/* && \
    corepack enable && \
    mkdir /tmp/pnpm-store && \
    pnpm install --frozen-lockfile --store-dir /tmp/pnpm-store && \
    rm -rf /tmp/pnpm-store

# Build the plugin server.
#
# Note: we run the build as a separate action to increase
# the cache hit ratio of the layers above.
COPY ./src/ ./src/
RUN pnpm build

# As the plugin-server is now built, let’s keep
# only prod dependencies in the node_module folder
# as we will copy it to the last image.
RUN corepack enable && \
    mkdir /tmp/pnpm-store && \
    pnpm install --frozen-lockfile --store-dir /tmp/pnpm-store --prod && \
    rm -rf /tmp/pnpm-store


#
# ---------------------------------------------------------
#
FROM node:18.12.1-bullseye-slim

# Install and use a non-root user.
RUN groupadd -g 1000 posthog && \
    useradd -u 999 -r -g posthog posthog && \
    chown posthog:posthog /code
USER posthog

# Add in the compiled plugin-server & its runtime dependencies from the plugin-server-build stage.
COPY --from=plugin-server-build --chown=posthog:posthog /code/plugin-server/dist /code/plugin-server/dist
COPY --from=plugin-server-build --chown=posthog:posthog /code/plugin-server/node_modules /code/plugin-server/node_modules
COPY --from=plugin-server-build --chown=posthog:posthog /code/plugin-server/package.json /code/plugin-server/package.json
