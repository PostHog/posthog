#
# This Dockerfile is used for self-hosted production builds.
#
# PostHog has sunset support for self-hosted K8s deployments.
# See: https://posthog.com/blog/sunsetting-helm-support-posthog
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
FROM node:22.17.1-bookworm-slim AS frontend-build
WORKDIR /code
SHELL ["/bin/bash", "-e", "-o", "pipefail", "-c"]

COPY turbo.json package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.json ./
COPY frontend/package.json frontend/
COPY frontend/bin/ frontend/bin/
COPY bin/ bin/
COPY patches/ patches/
COPY common/hogvm/typescript/ common/hogvm/typescript/
COPY common/esbuilder/ common/esbuilder/
COPY common/tailwind/ common/tailwind/
COPY products/ products/
COPY ee/frontend/ ee/frontend/
COPY .git/config .git/config
COPY .git/HEAD .git/HEAD
COPY .git/refs/heads .git/refs/heads
RUN --mount=type=cache,id=pnpm,target=/tmp/pnpm-store-v23 \
    corepack enable && pnpm --version && \
    pnpm --filter=@posthog/frontend... install --frozen-lockfile --store-dir /tmp/pnpm-store-v23

COPY frontend/ frontend/
RUN bin/turbo --filter=@posthog/frontend build

# Process sourcemaps using posthog-cli
RUN --mount=type=secret,id=posthog_upload_sourcemaps_cli_api_key \
    if [ -f /run/secrets/posthog_upload_sourcemaps_cli_api_key ]; then \
    apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates curl && \
    curl --proto '=https' --tlsv1.2 -LsSf https://download.posthog.com/cli | sh && \
    export PATH="/root/.posthog:$PATH" && \
    export POSTHOG_CLI_TOKEN="$(cat /run/secrets/posthog_upload_sourcemaps_cli_api_key)" && \
    export POSTHOG_CLI_ENV_ID=2 && \
    posthog-cli --no-fail sourcemap process --directory /code/frontend/dist --public-path-prefix /static; \
    fi

#
# ---------------------------------------------------------
#
FROM ghcr.io/posthog/rust-node-container:bookworm_rust_1.88-node_22.17.1 AS plugin-server-build

# Compile and install system dependencies
# Add Confluent's client repository for librdkafka 2.10.1
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    "wget" \
    "gnupg" \
    && \
    mkdir -p /etc/apt/keyrings && \
    wget -qO - https://packages.confluent.io/clients/deb/archive.key | gpg --dearmor -o /etc/apt/keyrings/confluent-clients.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/confluent-clients.gpg] https://packages.confluent.io/clients/deb/ bookworm main" > /etc/apt/sources.list.d/confluent-clients.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    "make" \
    "g++" \
    "gcc" \
    "python3" \
    "librdkafka1=2.10.1-1.cflt~deb12" \
    "librdkafka++1=2.10.1-1.cflt~deb12" \
    "librdkafka-dev=2.10.1-1.cflt~deb12" \
    "libssl-dev=3.0.17-1~deb12u2" \
    "libssl3=3.0.17-1~deb12u2" \
    "zlib1g-dev" \
    && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /code
COPY turbo.json package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.json ./
COPY ./bin/turbo ./bin/turbo
COPY ./patches ./patches
COPY ./rust ./rust
COPY ./common/esbuilder/ ./common/esbuilder/
COPY ./common/plugin_transpiler/ ./common/plugin_transpiler/
COPY ./common/hogvm/typescript/ ./common/hogvm/typescript/
COPY ./plugin-server/package.json ./plugin-server/tsconfig.json ./plugin-server/
SHELL ["/bin/bash", "-e", "-o", "pipefail", "-c"]

# Use system librdkafka from Confluent (2.10.1) instead of bundled version
ENV BUILD_LIBRDKAFKA=0

# Compile and install Node.js dependencies.
# NOTE: we don't actually use the plugin-transpiler with the plugin-server, it's just here for the build.
RUN --mount=type=cache,id=pnpm,target=/tmp/pnpm-store-v23 \
    corepack enable && \
    NODE_OPTIONS="--max-old-space-size=16384" pnpm --filter=@posthog/plugin-server... install --frozen-lockfile --store-dir /tmp/pnpm-store-v23 && \
    NODE_OPTIONS="--max-old-space-size=16384" pnpm --filter=@posthog/plugin-transpiler... install --frozen-lockfile --store-dir /tmp/pnpm-store-v23 && \
    NODE_OPTIONS="--max-old-space-size=16384" bin/turbo --filter=@posthog/plugin-transpiler build

# Build the plugin server.
#
# Note: we run the build as a separate action to increase
# the cache hit ratio of the layers above.
COPY ./plugin-server/src/ ./plugin-server/src/
COPY ./plugin-server/tests/ ./plugin-server/tests/
COPY ./plugin-server/assets/ ./plugin-server/assets/

# Build cyclotron first with increased memory
RUN NODE_OPTIONS="--max-old-space-size=16384" bin/turbo --filter=@posthog/cyclotron build

# Then build the plugin server with increased memory
RUN NODE_OPTIONS="--max-old-space-size=16384" bin/turbo --filter=@posthog/plugin-server build

# only prod dependencies in the node_module folder
# as we will copy it to the last image.
RUN --mount=type=cache,id=pnpm,target=/tmp/pnpm-store-v23 \
    corepack enable && \
    NODE_OPTIONS="--max-old-space-size=16384" pnpm --filter=@posthog/plugin-server install --frozen-lockfile --store-dir /tmp/pnpm-store-v23 --prod && \
    NODE_OPTIONS="--max-old-space-size=16384" bin/turbo --filter=@posthog/plugin-server prepare

#
# ---------------------------------------------------------
#
# Same as pyproject.toml so that uv can pick it up and doesn't need to download a different Python version.
FROM python:3.12.11-slim-bookworm AS posthog-build
WORKDIR /code
SHELL ["/bin/bash", "-e", "-o", "pipefail", "-c"]

# Compile and install Python dependencies.
# We install those dependencies on a custom folder that we will
# then copy to the last image.
COPY pyproject.toml uv.lock ./
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    "build-essential" \
    "git" \
    "libpq-dev" \
    "libxmlsec1" \
    "libxmlsec1-dev" \
    "libffi-dev" \
    "zlib1g-dev" \
    "pkg-config" \
    && \
    rm -rf /var/lib/apt/lists/* && \
    pip install uv==0.8.19 --no-cache-dir && \
    UV_PROJECT_ENVIRONMENT=/python-runtime uv sync --frozen --no-dev --no-cache --compile-bytecode --no-binary-package lxml --no-binary-package xmlsec

ENV PATH=/python-runtime/bin:$PATH \
    PYTHONPATH=/python-runtime

# Add in Django deps and generate Django's static files.
COPY manage.py manage.py
COPY common/esbuilder common/esbuilder
COPY common/hogvm common/hogvm/
COPY posthog posthog/
COPY products/ products/
COPY ee ee/
COPY --from=frontend-build /code/frontend/dist /code/frontend/dist
RUN SKIP_SERVICE_VERSION_REQUIREMENTS=1 STATIC_COLLECTION=1 DATABASE_URL='postgres:///' REDIS_URL='redis:///' python manage.py collectstatic --noinput



#
# ---------------------------------------------------------
#
FROM debian:bookworm-slim AS fetch-geoip-db
WORKDIR /code
SHELL ["/bin/bash", "-e", "-o", "pipefail", "-c"]

# Fetch the GeoLite2-City database that will be used for IP geolocation within Django.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    "ca-certificates" \
    "curl" \
    "brotli" \
    && \
    rm -rf /var/lib/apt/lists/* && \
    mkdir share && \
    ( curl -s -L "https://mmdbcdn.posthog.net/" --http1.1 | brotli --decompress --output=./share/GeoLite2-City.mmdb ) && \
    chmod -R 755 ./share/GeoLite2-City.mmdb


#
# ---------------------------------------------------------
#
# NOTE: v1.32 is running bullseye, v1.33 is running bookworm
FROM unit:1.33.0-python3.12
WORKDIR /code
SHELL ["/bin/bash", "-e", "-o", "pipefail", "-c"]
ENV PYTHONUNBUFFERED 1

# Install OS runtime dependencies.
# Note: please add in this stage runtime dependences only!
# Add Confluent's client repository for librdkafka runtime
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    "wget" \
    "gnupg" \
    && \
    mkdir -p /etc/apt/keyrings && \
    wget -qO - https://packages.confluent.io/clients/deb/archive.key | gpg --dearmor -o /etc/apt/keyrings/confluent-clients.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/confluent-clients.gpg] https://packages.confluent.io/clients/deb/ bookworm main" > /etc/apt/sources.list.d/confluent-clients.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    "chromium" \
    "chromium-driver" \
    "libpq-dev" \
    "libxmlsec1" \
    "libxmlsec1-dev" \
    "libxml2" \
    "gettext-base" \
    "ffmpeg=7:5.1.7-0+deb12u1" \
    "librdkafka1=2.10.1-1.cflt~deb12" \
    "librdkafka++1=2.10.1-1.cflt~deb12" \
    "libssl-dev=3.0.17-1~deb12u2" \
    "libssl3=3.0.17-1~deb12u2" \
    "libjemalloc2" \
    && \
    rm -rf /var/lib/apt/lists/*

# Install MS SQL dependencies
RUN curl https://packages.microsoft.com/keys/microsoft.asc | tee /etc/apt/trusted.gpg.d/microsoft.asc && \
    curl https://packages.microsoft.com/config/debian/11/prod.list | tee /etc/apt/sources.list.d/mssql-release.list && \
    apt-get update && \
    ACCEPT_EULA=Y apt-get install -y msodbcsql18 && \
    rm -rf /var/lib/apt/lists/*

# Install Node.js 22.17.1 with architecture detection and verification
ENV NODE_VERSION 22.17.1

RUN ARCH= && dpkgArch="$(dpkg --print-architecture)" \
    && case "${dpkgArch##*-}" in \
    amd64) ARCH='x64';; \
    ppc64el) ARCH='ppc64le';; \
    s390x) ARCH='s390x';; \
    arm64) ARCH='arm64';; \
    armhf) ARCH='armv7l';; \
    i386) ARCH='x86';; \
    *) echo "unsupported architecture"; exit 1 ;; \
    esac \
    && export GNUPGHOME="$(mktemp -d)" \
    && set -ex \
    && for key in \
    5BE8A3F6C8A5C01D106C0AD820B1A390B168D356 \
    C0D6248439F1D5604AAFFB4021D900FFDB233756 \
    DD792F5973C6DE52C432CBDAC77ABFA00DDBF2B7 \
    CC68F5A3106FF448322E48ED27F5E38D5B0A215F \
    8FCCA13FEF1D0C2E91008E09770F7A9A5AE15600 \
    890C08DB8579162FEE0DF9DB8BEAB4DFCF555EF4 \
    C82FA3AE1CBEDC6BE46B9360C43CEC45C17AB93C \
    108F52B48DB57BB0CC439B2997B01419BD92F80A \
    A363A499291CBBC940DD62E41F10027AF002F8B0 \
    ; do \
    { gpg --batch --keyserver hkps://keys.openpgp.org --recv-keys "$key" && gpg --batch --fingerprint "$key"; } || \
    { gpg --batch --keyserver keyserver.ubuntu.com --recv-keys "$key" && gpg --batch --fingerprint "$key"; } ; \
    done \
    && curl -fsSLO --compressed "https://nodejs.org/dist/v$NODE_VERSION/node-v$NODE_VERSION-linux-$ARCH.tar.xz" \
    && curl -fsSLO --compressed "https://nodejs.org/dist/v$NODE_VERSION/SHASUMS256.txt.asc" \
    && gpg --batch --decrypt --output SHASUMS256.txt SHASUMS256.txt.asc \
    && gpgconf --kill all \
    && rm -rf "$GNUPGHOME" \
    && grep " node-v$NODE_VERSION-linux-$ARCH.tar.xz\$" SHASUMS256.txt | sha256sum -c - \
    && tar -xJf "node-v$NODE_VERSION-linux-$ARCH.tar.xz" -C /usr/local --strip-components=1 --no-same-owner \
    && rm "node-v$NODE_VERSION-linux-$ARCH.tar.xz" SHASUMS256.txt.asc SHASUMS256.txt \
    && ln -s /usr/local/bin/node /usr/local/bin/nodejs \
    && node --version \
    && npm --version \
    && rm -rf /tmp/*

# Install and use a non-root user.
RUN groupadd -g 1000 posthog && \
    useradd -r -g posthog posthog && \
    chown posthog:posthog /code
USER posthog

# Add the commit hash
ARG COMMIT_HASH
RUN echo $COMMIT_HASH > /code/commit.txt

# Add in the compiled plugin-server & its runtime dependencies from the plugin-server-build stage.
COPY --from=plugin-server-build --chown=posthog:posthog /code/rust/cyclotron-node/dist /code/rust/cyclotron-node/dist
COPY --from=plugin-server-build --chown=posthog:posthog /code/rust/cyclotron-node/package.json /code/rust/cyclotron-node/package.json
COPY --from=plugin-server-build --chown=posthog:posthog /code/rust/cyclotron-node/index.node /code/rust/cyclotron-node/index.node
COPY --from=plugin-server-build --chown=posthog:posthog /code/common/plugin_transpiler/dist /code/common/plugin_transpiler/dist
COPY --from=plugin-server-build --chown=posthog:posthog /code/common/plugin_transpiler/node_modules /code/common/plugin_transpiler/node_modules
COPY --from=plugin-server-build --chown=posthog:posthog /code/common/plugin_transpiler/package.json /code/common/plugin_transpiler/package.json
COPY --from=plugin-server-build --chown=posthog:posthog /code/common/hogvm/typescript/dist /code/common/hogvm/typescript/dist
COPY --from=plugin-server-build --chown=posthog:posthog /code/common/hogvm/typescript/node_modules /code/common/hogvm/typescript/node_modules
COPY --from=plugin-server-build --chown=posthog:posthog /code/plugin-server/dist /code/plugin-server/dist
COPY --from=plugin-server-build --chown=posthog:posthog /code/node_modules /code/node_modules
COPY --from=plugin-server-build --chown=posthog:posthog /code/plugin-server/node_modules /code/plugin-server/node_modules
COPY --from=plugin-server-build --chown=posthog:posthog /code/plugin-server/package.json /code/plugin-server/package.json
COPY --from=plugin-server-build --chown=posthog:posthog /code/plugin-server/assets /code/plugin-server/assets

# Copy the Python dependencies and Django staticfiles from the posthog-build stage.
COPY --from=posthog-build --chown=posthog:posthog /code/staticfiles /code/staticfiles
COPY --from=posthog-build --chown=posthog:posthog /python-runtime /python-runtime
ENV PATH=/python-runtime/bin:$PATH \
    PYTHONPATH=/python-runtime

# Install Playwright Chromium browser for video export (as root for system deps)
USER root
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN /python-runtime/bin/python -m playwright install --with-deps chromium && \
    chown -R posthog:posthog /ms-playwright
USER posthog

# Validate video export dependencies
RUN ffmpeg -version
RUN /python-runtime/bin/python -c "import playwright; print('Playwright package imported successfully')"
RUN /python-runtime/bin/python -c "from playwright.sync_api import sync_playwright; print('Playwright sync API available')"

# Copy the frontend assets from the frontend-build stage.
# TODO: this copy should not be necessary, we should remove it once we verify everything still works.
COPY --from=frontend-build --chown=posthog:posthog /code/frontend/dist /code/frontend/dist

# Copy the GeoLite2-City database from the fetch-geoip-db stage.
COPY --from=fetch-geoip-db --chown=posthog:posthog /code/share/GeoLite2-City.mmdb /code/share/GeoLite2-City.mmdb

# Add in the Gunicorn config, custom bin files and Django deps.
COPY --chown=posthog:posthog gunicorn.config.py ./
COPY --chown=posthog:posthog ./bin ./bin/
COPY --chown=posthog:posthog manage.py manage.py
COPY --chown=posthog:posthog posthog posthog/
COPY --chown=posthog:posthog ee ee/
COPY --chown=posthog:posthog common/hogvm common/hogvm/
COPY --chown=posthog:posthog dags dags/
COPY --chown=posthog:posthog products products/

# Keep server command backwards compatible
RUN cp ./bin/docker-server-unit ./bin/docker-server

# Setup ENV.
ENV NODE_ENV=production \
    CHROME_BIN=/usr/bin/chromium \
    CHROME_PATH=/usr/lib/chromium/ \
    CHROMEDRIVER_BIN=/usr/bin/chromedriver \
    BUILD_LIBRDKAFKA=0 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Expose container port and run entry point script.
EXPOSE 8000

# Expose the port from which we serve OpenMetrics data.
EXPOSE 8001
COPY unit.json.tpl /docker-entrypoint.d/unit.json.tpl
USER root
CMD ["./bin/docker"]
