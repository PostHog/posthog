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
# - sourcemap-upload: upload sourcemaps to PostHog (isolated, no artifacts)
# - nodejs-build: build nodejs (Node.js app) & fetch its runtime dependencies
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
COPY docs/onboarding/ docs/onboarding/
RUN --mount=type=cache,id=pnpm,target=/tmp/pnpm-store-v24 \
    corepack enable && pnpm --version && \
    CI=1 pnpm --filter=@posthog/frontend... install --frozen-lockfile --store-dir /tmp/pnpm-store-v24

COPY frontend/ frontend/
RUN bin/turbo --filter=@posthog/frontend build


#
# ---------------------------------------------------------
#
# Isolated stage for sourcemap upload - keeps secrets and external network calls
# out of the main build cache. This stage produces no artifacts for the final image.
#
FROM node:22.17.1-bookworm-slim AS sourcemap-upload
WORKDIR /code
SHELL ["/bin/bash", "-e", "-o", "pipefail", "-c"]

ARG COMMIT_HASH

COPY --from=frontend-build /code/frontend/dist /code/frontend/dist

RUN --mount=type=secret,id=posthog_upload_sourcemaps_cli_api_key \
    ( \
        if [ -f /run/secrets/posthog_upload_sourcemaps_cli_api_key ]; then \
            apt-get update && \
            apt-get install -y --no-install-recommends ca-certificates curl && \
            curl --proto '=https' --tlsv1.2 -LsSf https://download.posthog.com/cli | sh && \
            export PATH="/root/.posthog:$PATH" && \
            export POSTHOG_CLI_TOKEN="$(cat /run/secrets/posthog_upload_sourcemaps_cli_api_key)" && \
            export POSTHOG_CLI_ENV_ID=2 && \
            posthog-cli --no-fail sourcemap process \
                --directory /code/frontend/dist \
                --public-path-prefix /static \
                --project posthog \
                --version "${COMMIT_HASH:-unknown}"; \
        fi \
    ) || true && \
    touch /tmp/.sourcemaps-processed


#
# ---------------------------------------------------------
#
FROM ghcr.io/posthog/rust-node-container:bookworm_rust_1.88-node_22.17.1 AS nodejs-build

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
COPY ./nodejs/package.json ./nodejs/tsconfig.json ./nodejs/
SHELL ["/bin/bash", "-e", "-o", "pipefail", "-c"]

# Use system librdkafka from Confluent (2.10.1) instead of bundled version
ENV BUILD_LIBRDKAFKA=0

# Compile and install Node.js dependencies.
# NOTE: we don't actually use the plugin-transpiler with the nodejs, it's just here for the build.
RUN --mount=type=cache,id=pnpm,target=/tmp/pnpm-store-v24 \
    corepack enable && \
    NODE_OPTIONS="--max-old-space-size=16384" CI=1 pnpm --filter=@posthog/nodejs... install --frozen-lockfile --store-dir /tmp/pnpm-store-v24 && \
    NODE_OPTIONS="--max-old-space-size=16384" CI=1 pnpm --filter=@posthog/plugin-transpiler... install --frozen-lockfile --store-dir /tmp/pnpm-store-v24 && \
    NODE_OPTIONS="--max-old-space-size=16384" bin/turbo --filter=@posthog/plugin-transpiler build

# Build the nodejs services.
#
# Note: we run the build as a separate action to increase
# the cache hit ratio of the layers above.
COPY ./nodejs/src/ ./nodejs/src/
COPY ./nodejs/tests/ ./nodejs/tests/
COPY ./nodejs/assets/ ./nodejs/assets/
COPY ./nodejs/bin/ ./nodejs/bin/

# Build cyclotron first
RUN NODE_OPTIONS="--max-old-space-size=16384" bin/turbo --filter=@posthog/cyclotron build

# Then build the nodejs services
RUN NODE_OPTIONS="--max-old-space-size=16384" bin/turbo --filter=@posthog/nodejs build

#
# ---------------------------------------------------------
#
FROM ghcr.io/astral-sh/uv:0.9.9 AS uv

# Same as pyproject.toml so that uv can pick it up and doesn't need to download a different Python version.
FROM python:3.12.12-slim-bookworm@sha256:78e702aee4d693e769430f0d7b4f4858d8ea3f1118dc3f57fee3f757d0ca64b1 AS posthog-build
COPY --from=uv /uv /uvx /bin/
WORKDIR /code
SHELL ["/bin/bash", "-e", "-o", "pipefail", "-c"]

# uv settings for Docker builds
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_PROJECT_ENVIRONMENT=/python-runtime

# Install build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    "build-essential" \
    "git" \
    "libpq-dev" \
    "libxmlsec1=1.2.37-2" \
    "libxmlsec1-dev=1.2.37-2" \
    "libffi-dev" \
    "zlib1g-dev" \
    "pkg-config" \
    && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies using cache mount for faster rebuilds
# Cache ID includes libxmlsec1 version to bust cache when system library changes
RUN --mount=type=cache,id=uv-libxmlsec1.2.37-2,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project --no-binary-package lxml --no-binary-package xmlsec

ENV PATH=/python-runtime/bin:$PATH \
    PYTHONPATH=/python-runtime

# Add in Django deps
COPY manage.py manage.py
COPY common/esbuilder common/esbuilder
COPY common/hogvm common/hogvm/
COPY posthog posthog/
COPY products/ products/
COPY ee ee/

# Copy the built frontend assets and also the products.json file
COPY --from=frontend-build /code/frontend/dist /code/frontend/dist
COPY --from=frontend-build /code/frontend/src/products.json /code/frontend/src/products.json

# Make sure we build the static files
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
    "libxmlsec1=1.2.37-2" \
    "libxmlsec1-dev=1.2.37-2" \
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

# Add in the compiled nodejs & its runtime dependencies from the nodejs-build stage.
COPY --from=nodejs-build --chown=posthog:posthog /code/rust/cyclotron-node/dist /code/rust/cyclotron-node/dist
COPY --from=nodejs-build --chown=posthog:posthog /code/rust/cyclotron-node/package.json /code/rust/cyclotron-node/package.json
COPY --from=nodejs-build --chown=posthog:posthog /code/rust/cyclotron-node/index.node /code/rust/cyclotron-node/index.node
COPY --from=nodejs-build --chown=posthog:posthog /code/common/plugin_transpiler/dist /code/common/plugin_transpiler/dist
COPY --from=nodejs-build --chown=posthog:posthog /code/common/plugin_transpiler/node_modules /code/common/plugin_transpiler/node_modules
COPY --from=nodejs-build --chown=posthog:posthog /code/common/plugin_transpiler/package.json /code/common/plugin_transpiler/package.json
COPY --from=nodejs-build --chown=posthog:posthog /code/common/hogvm/typescript/dist /code/common/hogvm/typescript/dist
COPY --from=nodejs-build --chown=posthog:posthog /code/common/hogvm/typescript/node_modules /code/common/hogvm/typescript/node_modules
COPY --from=nodejs-build --chown=posthog:posthog /code/nodejs/dist /code/nodejs/dist
COPY --from=nodejs-build --chown=posthog:posthog /code/node_modules /code/node_modules
COPY --from=nodejs-build --chown=posthog:posthog /code/nodejs/node_modules /code/nodejs/node_modules
COPY --from=nodejs-build --chown=posthog:posthog /code/nodejs/package.json /code/nodejs/package.json
COPY --from=nodejs-build --chown=posthog:posthog /code/nodejs/assets /code/nodejs/assets
COPY --from=nodejs-build --chown=posthog:posthog /code/nodejs/bin /code/nodejs/bin

# Copy the Python dependencies and Django staticfiles from the posthog-build stage.
COPY --from=posthog-build --chown=posthog:posthog /code/staticfiles /code/staticfiles
COPY --from=posthog-build --chown=posthog:posthog /python-runtime /python-runtime
ENV PATH=/python-runtime/bin:$PATH \
    PYTHONPATH=/python-runtime

# Install Playwright Chromium browser for video export (as root for system deps)
# Use cache mount for browser binaries to avoid re-downloading on every build
USER root
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN --mount=type=cache,id=playwright-browsers,target=/tmp/playwright-cache \
    PLAYWRIGHT_BROWSERS_PATH=/tmp/playwright-cache \
    /python-runtime/bin/python -m playwright install --with-deps chromium && \
    mkdir -p /ms-playwright && \
    cp -r /tmp/playwright-cache/* /ms-playwright/ && \
    chown -R posthog:posthog /ms-playwright
USER posthog

# Validate video export dependencies
RUN ffmpeg -version
RUN /python-runtime/bin/python -c "import playwright; print('Playwright package imported successfully')"
RUN /python-runtime/bin/python -c "from playwright.sync_api import sync_playwright; print('Playwright sync API available')"

# Copy the frontend assets from the frontend-build stage.
# TODO: this copy should not be necessary, we should remove it once we verify everything still works.
COPY --from=frontend-build --chown=posthog:posthog /code/frontend/dist /code/frontend/dist

# Ensure sourcemap-upload stage runs (the file itself is not needed in the final image).
COPY --from=sourcemap-upload /tmp/.sourcemaps-processed /tmp/.sourcemaps-processed

# Copy products.json from the frontend-build stage
COPY --from=frontend-build --chown=posthog:posthog /code/frontend/src/products.json /code/frontend/src/products.json

# Copy the GeoLite2-City database from the fetch-geoip-db stage.
COPY --from=fetch-geoip-db --chown=posthog:posthog /code/share/GeoLite2-City.mmdb /code/share/GeoLite2-City.mmdb

# Add in custom bin files and Django deps.
COPY --chown=posthog:posthog ./bin ./bin/
COPY --chown=posthog:posthog manage.py manage.py
COPY --chown=posthog:posthog posthog posthog/
COPY --chown=posthog:posthog ee ee/
COPY --chown=posthog:posthog common/hogvm common/hogvm/
COPY --chown=posthog:posthog products products/

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
# nosemgrep: dockerfile.security.last-user-is-root.last-user-is-root
USER root
CMD ["./bin/docker"]
