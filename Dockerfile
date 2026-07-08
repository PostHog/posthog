#
# This Dockerfile is used for self-hosted production builds.
#
# PostHog has sunset support for self-hosted K8s deployments.
# See: https://posthog.com/blog/sunsetting-helm-support-posthog
#
# Note: PostHog Cloud uses this same image (re-tagged to ECR posthog-cloud); there is no separate Dockerfile.cloud.
#
# The stages are used to:
#
# - frontend-build: build the frontend (static assets)
# - sourcemap-upload: upload sourcemaps to PostHog (isolated, no artifacts)
# - node-scripts-build: build plugin transpiler and other Node.js build artifacts
# - posthog-build: fetch PostHog (Django app) dependencies & build Django collectstatic
# - fetch-geoip-db: fetch the GeoIP database
#
# Node.js services are built separately using Dockerfile.node.
#
# In the last stage, we import the artifacts from the previous
# stages, add some runtime dependencies and build the final image.
#


#
# ---------------------------------------------------------
#
FROM node:24.13.0-bookworm-slim AS frontend-build
WORKDIR /code
SHELL ["/bin/bash", "-e", "-o", "pipefail", "-c"]

COPY turbo.json package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.json ./
COPY frontend/package.json frontend/
COPY frontend/bin/ frontend/bin/
COPY bin/ bin/
COPY patches/ patches/
COPY common/hogvm/typescript/ common/hogvm/typescript/
COPY common/esbuilder/ common/esbuilder/
COPY common/replay-shared/ common/replay-shared/
COPY common/tailwind/ common/tailwind/
COPY packages/quill/ packages/quill/
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
FROM node:24.13.0-bookworm-slim AS sourcemap-upload
WORKDIR /code
SHELL ["/bin/bash", "-e", "-o", "pipefail", "-c"]

ARG COMMIT_HASH

COPY --from=frontend-build /code/frontend/dist /code/frontend/dist

# Upload sourcemaps to error tracking, recording whether it GENUINELY succeeded so the later strip
# only deletes the .map files when an uploaded copy exists. The build never fails on a sourcemap
# problem (missing secret, CLI download / network / auth failure): in that case the status is
# "retained" and the .map files are kept in the image. Uses explicit && chaining rather than `set -e`,
# which bash ignores inside a `||`-guarded subshell — any failing link drops us into the retained branch.
#
# The CLI installer is pinned to an immutable release tag and checksum-verified before execution:
# the processed frontend/dist ships in the final image, so the CLI must not be mutable remote code.
# To upgrade, change POSTHOG_CLI_VERSION and recompute the hash:
#   curl -LsSf "https://github.com/PostHog/posthog/releases/download/posthog-cli%2Fv<X.Y.Z>/posthog-cli-installer.sh" | sha256sum
ARG POSTHOG_CLI_VERSION=0.7.22
ARG POSTHOG_CLI_INSTALLER_SHA256=9bfeafcfb6f3acd2d15e3fad267b3c22b26d6aa0a28497e3f1a214f143f66219
RUN --mount=type=secret,id=posthog_upload_sourcemaps_cli_api_key \
    if ( \
        [ -f /run/secrets/posthog_upload_sourcemaps_cli_api_key ] && \
        apt-get update && \
        apt-get install -y --no-install-recommends ca-certificates curl && \
        curl --proto '=https' --tlsv1.2 -LsSf -o /tmp/posthog-cli-installer.sh \
            "https://github.com/PostHog/posthog/releases/download/posthog-cli%2Fv${POSTHOG_CLI_VERSION}/posthog-cli-installer.sh" && \
        echo "${POSTHOG_CLI_INSTALLER_SHA256}  /tmp/posthog-cli-installer.sh" | sha256sum -c - && \
        sh /tmp/posthog-cli-installer.sh && \
        export PATH="/root/.posthog:$PATH" && \
        export POSTHOG_CLI_TOKEN="$(cat /run/secrets/posthog_upload_sourcemaps_cli_api_key)" && \
        export POSTHOG_CLI_ENV_ID=2 && \
        posthog-cli sourcemap process \
            --directory /code/frontend/dist \
            --public-path-prefix /static \
            --project posthog \
            --version "${COMMIT_HASH:-unknown}" \
    ); then \
        echo uploaded > /tmp/.sourcemaps-status; \
    else \
        echo "WARNING: sourcemaps not uploaded (no secret or upload failed); .map files will be retained in the image" >&2; \
        echo retained > /tmp/.sourcemaps-status; \
    fi && \
    touch /tmp/.sourcemaps-processed


#
# ---------------------------------------------------------
#
# Build plugin transpiler and other Node.js build artifacts.
#
FROM node:24.13.0-bookworm-slim AS node-scripts-build
WORKDIR /code
SHELL ["/bin/bash", "-e", "-o", "pipefail", "-c"]
# Build plugin transpiler for site destinations/apps
COPY turbo.json package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.json ./
COPY bin/turbo bin/turbo
COPY patches/ patches/
COPY common/esbuilder/ common/esbuilder/
COPY common/plugin_transpiler/ common/plugin_transpiler/
RUN --mount=type=cache,id=pnpm,target=/tmp/pnpm-store-v24 \
    corepack enable && \
    NODE_OPTIONS="--max-old-space-size=4096" CI=1 pnpm --filter=@posthog/plugin-transpiler... install --frozen-lockfile --store-dir /tmp/pnpm-store-v24 && \
    NODE_OPTIONS="--max-old-space-size=4096" bin/turbo --filter=@posthog/plugin-transpiler build

# The transpiler bundle externalizes @babel/standalone (its only external runtime require — a
# self-contained 24MB package with no deps). Materialize it as real files inside the transpiler's
# own node_modules, replacing the pnpm symlink that pointed into the root node_modules. The final
# image then carries just this package instead of the entire ~469MB root /code/node_modules.
RUN cd /code/common/plugin_transpiler && \
    BABEL_REAL=$(node -e "process.stdout.write(require('path').dirname(require.resolve('@babel/standalone/package.json')))") && \
    rm -rf node_modules/@babel/standalone && \
    mkdir -p node_modules/@babel && \
    cp -rL "$BABEL_REAL" node_modules/@babel/standalone


#
# ---------------------------------------------------------
#
FROM ghcr.io/astral-sh/uv:0.11.14 AS uv

# Same as pyproject.toml so that uv can pick it up and doesn't need to download a different Python version.
FROM python:3.13.13-slim-bookworm@sha256:355bfa66770995d7e9a0da4b3473b44d0cb451f6b56f5615ad9c39e3c4eca03f AS posthog-build
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
    --mount=type=bind,source=tools/hogli,target=tools/hogli \
    uv sync --locked --no-dev --no-install-project --no-binary-package lxml --no-binary-package xmlsec

ENV PATH=/python-runtime/bin:$PATH \
    PYTHONPATH=/python-runtime

# Add in Django deps
COPY manage.py manage.py
COPY common/esbuilder common/esbuilder
COPY common/hogvm common/hogvm/
COPY common/migration_utils common/migration_utils/
COPY posthog posthog/
COPY products/ products/
COPY ee ee/

# Copy the sourcemap-processed frontend assets and also the products.json file. The CLI injects
# chunk IDs into JS before uploading maps, so the runtime JS must come from the same processed tree.
COPY --from=sourcemap-upload /code/frontend/dist /code/frontend/dist
COPY --from=frontend-build /code/frontend/src/products.json /code/frontend/src/products.json

# Make sure we build the static files
RUN SKIP_SERVICE_VERSION_REQUIREMENTS=1 STATIC_COLLECTION=1 DATABASE_URL='postgres:///' REDIS_URL='redis:///' python manage.py collectstatic --noinput

# Strip JS sourcemaps (~2.8GB) from the artifacts that ship in the final image — but ONLY when the
# isolated sourcemap-upload stage confirmed a real upload to error tracking (status "uploaded"). If the
# upload failed or no secret was provided, the .map files are kept so the only remaining copy isn't
# lost. Done here (not in the final stage) so the bytes never enter the COPYed layers.
COPY --from=sourcemap-upload /tmp/.sourcemaps-status /tmp/.sourcemaps-status
RUN if [ "$(cat /tmp/.sourcemaps-status)" = uploaded ]; then \
        echo "sourcemaps uploaded — stripping .map files from the image"; \
        find /code/staticfiles /code/frontend/dist -name '*.map' -delete; \
    else \
        echo "sourcemaps NOT uploaded — retaining .map files in the image"; \
    fi



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
# NOTE: v1.32 is running bullseye, v1.33+ is running bookworm
FROM unit:1.34.2-python3.13
WORKDIR /code
SHELL ["/bin/bash", "-e", "-o", "pipefail", "-c"]
ENV PYTHONUNBUFFERED 1
# Unit embeds libpython instead of launching the python3 CLI, so PEP 538 C-locale
# coercion never runs and open() defaults to ASCII under the container's bare locale.
# Force UTF-8 so file reads with non-ASCII bytes don't raise UnicodeDecodeError.
ENV PYTHONUTF8 1
ENV LANG C.UTF-8
ARG UNIT_GIT_TAG=1.35.0
ARG UNIT_GIT_REF=28404105810f53c570523c3e70006ad0ca210e58

# Build Unit from the upstream 1.35.0 release ref to ensure the Django 5 ASGI fix is present even when Docker tags lag.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    "build-essential" \
    "git" \
    "libpcre2-dev" \
    "zlib1g-dev" \
    && \
    git clone --depth 1 --branch "$UNIT_GIT_TAG" https://github.com/nginx/unit.git /tmp/unit && \
    cd /tmp/unit && \
    test "$(git rev-parse HEAD)" = "$UNIT_GIT_REF" && \
    NCPU="$(getconf _NPROCESSORS_ONLN)" && \
    DEB_HOST_MULTIARCH="$(gcc -print-multiarch)" && \
    CONFIGURE_ARGS="--prefix=/usr \
        --statedir=/var/lib/unit \
        --control=unix:/var/run/control.unit.sock \
        --runstatedir=/var/run \
        --pid=/var/run/unit.pid \
        --logdir=/var/log \
        --log=/var/log/unit.log \
        --tmpdir=/var/tmp \
        --user=unit \
        --group=unit \
        --openssl \
        --libdir=/usr/lib/$DEB_HOST_MULTIARCH \
        --modulesdir=/usr/lib/unit/modules" && \
    ./configure $CONFIGURE_ARGS && \
    make -j "$NCPU" unitd && \
    install -pm755 build/sbin/unitd /usr/sbin/unitd && \
    make clean && \
    ./configure $CONFIGURE_ARGS && \
    ./configure python --config=/usr/local/bin/python3-config && \
    make -j "$NCPU" python3-install && \
    rm -rf /tmp/unit && \
    apt-get purge -y --auto-remove "build-essential" "git" "libpcre2-dev" "zlib1g-dev" && \
    rm -rf /var/lib/apt/lists/*

# Install OS runtime dependencies.
# Note: please add in this stage runtime dependences only!
# Runtime-only shared libs: lxml/xmlsec are compiled --no-binary in the build stage (which keeps
# its own -dev headers), so the final image needs the runtime .so, not the -dev headers/static libs.
# libxmlsec1-openssl provides the OpenSSL crypto backend that libxmlsec1-dev used to pull in.
RUN apt-get update && \
    apt-get install -y --no-install-recommends --allow-downgrades \
    "gettext-base" \
    "libpq5" \
    "libxmlsec1=1.2.37-2" \
    "libxmlsec1-openssl=1.2.37-2" \
    "libxml2" \
    # libssl pinned to the 3.0 series (ABI-stable), not an exact version: Debian rotates
    # point releases out of the security archive, which breaks exact pins on uncached builds.
    "libssl3=3.0.*" \
    "libjemalloc2" \
    && \
    rm -rf /var/lib/apt/lists/*

# Note: no MS SQL ODBC driver is installed — the data-warehouse MSSQL source uses pymssql, which
# bundles FreeTDS in its wheel and does not use msodbcsql18/unixodbc (there is no pyodbc in the tree).

# Install Node.js 24.13.0 for standalone scripts with architecture detection and verification.
# Only the `node` binary is used at runtime (the plugin transpiler subprocess), so npm/npx/corepack/
# headers are stripped after install. Note: the dev-only `create_channel_definitions_file` management
# command shells out to `npx prettier` to regenerate a checked-in file; it is not run in this image.
ENV NODE_VERSION 24.13.0

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
    && rm -rf /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/corepack /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/corepack /usr/local/include/node \
    && rm -rf /tmp/*

# Install and use a non-root user.
# Pin uid/gid to a fixed, host-safe value (avoid 1000, which maps to ec2-user on the nodes).
RUN groupadd -g 10001 posthog && \
    useradd -u 10001 -g posthog -m -d /home/posthog -s /bin/bash posthog && \
    chown posthog:posthog /code
USER posthog

# Add the commit hash
ARG COMMIT_HASH
RUN echo $COMMIT_HASH > /code/commit.txt

# Copy the Python dependencies and Django staticfiles from the posthog-build stage.
COPY --from=posthog-build --chown=posthog:posthog /code/staticfiles /code/staticfiles
COPY --from=posthog-build --chown=posthog:posthog /python-runtime /python-runtime
ENV PATH=/python-runtime/bin:$PATH \
    PYTHONPATH=/python-runtime

# frontend/dist is read at runtime (Django template DIR in settings/web.py + the array.js disk
# fallback in js_snippet_versioning.py), so this COPY is load-bearing. Sourced from posthog-build,
# where the JS sourcemaps have already been stripped.
COPY --from=posthog-build --chown=posthog:posthog /code/frontend/dist /code/frontend/dist

# Ensure sourcemap-upload stage runs (the file itself is not needed in the final image).
COPY --from=sourcemap-upload /tmp/.sourcemaps-processed /tmp/.sourcemaps-processed

# Copy products.json from the frontend-build stage
COPY --from=frontend-build --chown=posthog:posthog /code/frontend/src/products.json /code/frontend/src/products.json

# Copy the GeoLite2-City database from the fetch-geoip-db stage.
COPY --from=fetch-geoip-db --chown=posthog:posthog /code/share/GeoLite2-City.mmdb /code/share/GeoLite2-City.mmdb

# Copy plugin transpiler (used by Django for site destinations/apps). The transpiler dist is a
# self-contained esbuild bundle (build.mjs uses bundle:true), so only its own dist + node_modules
# are needed at runtime — the full root /code/node_modules COPY was redundant.
COPY --from=node-scripts-build --chown=posthog:posthog /code/common/plugin_transpiler/dist /code/common/plugin_transpiler/dist
COPY --from=node-scripts-build --chown=posthog:posthog /code/common/plugin_transpiler/node_modules /code/common/plugin_transpiler/node_modules
COPY --from=node-scripts-build --chown=posthog:posthog /code/common/plugin_transpiler/package.json /code/common/plugin_transpiler/package.json

# Add in custom bin files and Django deps.
COPY --chown=posthog:posthog ./bin ./bin/
# Persons SQL migration files (read by apply_persons_migrations management command for hobby deploys)
COPY --chown=posthog:posthog ./rust/persons_migrations ./rust/persons_migrations/
COPY --chown=posthog:posthog manage.py manage.py
COPY --chown=posthog:posthog posthog posthog/
COPY --chown=posthog:posthog ee ee/
COPY --chown=posthog:posthog common/hogvm common/hogvm/
COPY --chown=posthog:posthog common/migration_utils common/migration_utils/
COPY --chown=posthog:posthog products products/

# Validate the Playwright client library (used to drive the remote browserless service over CDP —
# no browser binary ships in this image).
RUN /python-runtime/bin/python -c "import playwright; print('Playwright package imported successfully')"
RUN /python-runtime/bin/python -c "from playwright.sync_api import sync_playwright; print('Playwright sync API available')"

# Setup ENV.
ENV NODE_ENV=production

# Expose container port and run entry point script.
EXPOSE 8000

# Expose the port from which we serve OpenMetrics data.
EXPOSE 8001
COPY unit.json.tpl /docker-entrypoint.d/unit.json.tpl
# nosemgrep: dockerfile.security.last-user-is-root.last-user-is-root
USER root
CMD ["./bin/docker"]
