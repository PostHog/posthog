# Build the CDP server image. We use a multi-stage build to first build the CDP
# node application, then copy the built files to the final image.
#
# Note: separtely we bundle the resulting dist folder into the
# production.Dockerfile image such that the main image can run the entire
# application without needing to build the CDP server.
#
# We also need to copy the migrations folder as the CDP server needs it to
# run the migrations. The migrations use the Rust application sqlx-cli to
# run the migrations, so we need to copy the compiled binary from the Rust
# image. I'm sure there's a better way to do this, but this works for now.

FROM rust:1.68.2-slim-bullseye AS sqlx-cli-build

WORKDIR /code
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Since we are using the slim image, we need to install `pkg-config` and
# `libssl-dev` so cargo install completes successfully.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    "pkg-config" \
    "libssl-dev" \
    && \
    rm -rf /var/lib/apt/lists/*

# Install SQLx CLI.
RUN cargo install --version 0.6.3 sqlx-cli --no-default-features --features native-tls,postgres

FROM node:18.12.1-bullseye-slim AS cdp-build

WORKDIR /code
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install Node.js dependencies.
COPY package.json pnpm-lock.yaml ./
RUN corepack enable && \
    mkdir /tmp/pnpm-store && \
    pnpm install --frozen-lockfile --store-dir /tmp/pnpm-store && \
    rm -rf /tmp/pnpm-store

# Build the CDP server.
#
# Note: we run the build as a separate action to increase
# the cache hit ratio of the layers above.
COPY ./src/ ./src/
COPY tsconfig.json .swcrc ./
RUN pnpm build

# As the CDP server is now built, let’s keep only prod dependencies in the
# node_module folder as we will copy it to the last image. We remove all
# dependencies first to ensure we end up with the smallest possible image.
RUN rm -rf node_modules && \
    corepack enable && \
    mkdir /tmp/pnpm-store && \
    pnpm install --frozen-lockfile --store-dir /tmp/pnpm-store --prod && \
    rm -rf /tmp/pnpm-store

# Build the final image.
FROM node:18.12.1-bullseye-slim

WORKDIR /code
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install tini.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    "tini" \
    && \
    rm -rf /var/lib/apt/lists/*

# Copy the SQLx CLI binary from the previous stage.
COPY --from=sqlx-cli-build --link /usr/local/cargo/bin/sqlx /usr/local/bin/sqlx

# Copy the built CDP server from the previous stage.
COPY --from=cdp-build --link /code/node_modules/ ./node_modules/
COPY --from=cdp-build --link /code/dist/ ./dist/
COPY --link ./migrations/ ./migrations/

# Set [Tini](https://github.com/krallin/tini) as the entrypoint.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["node", "dist/rest.js"]
