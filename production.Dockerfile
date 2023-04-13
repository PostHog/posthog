#
# This Dockerfile is used for self-hosted production builds.
#
# Note: for PostHog Cloud remember to update ‘Dockerfile.cloud’ as appropriate.
#
# The stages are used to:
#
# - frontend-build: build the frontend (static assets)
# - plugin-server-build: build plugin-server (Node.js app) & fetch its runtime dependencies
# - posthog-build: fetch PostHog (Django app) dependencies & build Django collectstatic
# - fetch-geoip-db: fetch the GeoIP database
#
# In the last stage, we import the artifacts from the previous
# stages, add some runtime dependencies and build the final image.
#


#
# ---------------------------------------------------------
#
FROM node:18.12.1-bullseye-slim AS plugin-server-build
WORKDIR /code/plugin-server
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Compile and install Node.js dependencies.
COPY ./plugin-server/package.json ./plugin-server/pnpm-lock.yaml ./plugin-server/tsconfig.json ./
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    "make" \
    "g++" \
    "gcc" \
    "python3" \
    "libssl-dev" \
    "ca-certificates" \
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
COPY ./plugin-server/src/ ./src/
RUN pnpm build

# As the plugin-server is now built, let’s keep
# only prod dependencies in the node_module folder
# as we will copy it to the last image.
RUN corepack enable && \
    mkdir /tmp/pnpm-store && \
    pnpm install --frozen-lockfile --store-dir /tmp/pnpm-store --prod && \
    rm -rf /tmp/pnpm-store

