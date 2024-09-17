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
FROM node:18.19.1-bullseye-slim AS frontend-build
WORKDIR /code
SHELL ["/bin/bash", "-e", "-o", "pipefail", "-c"]

COPY package.json pnpm-lock.yaml ./
COPY patches/ patches/
RUN corepack enable && pnpm --version && \
    mkdir /tmp/pnpm-store && \
    pnpm install --frozen-lockfile --store-dir /tmp/pnpm-store --prod && \
    rm -rf /tmp/pnpm-store

COPY frontend/ frontend/
COPY ee/frontend/ ee/frontend/
COPY ./bin/ ./bin/
COPY babel.config.js tsconfig.json webpack.config.js tailwind.config.js ./
RUN pnpm build

#
# ---------------------------------------------------------
#
FROM ghcr.io/posthog/rust-node-container:bullseye_rust_1.80.1-node_18.19.1 AS plugin-server-build
WORKDIR /code
COPY ./rust ./rust
WORKDIR /code/plugin-server
SHELL ["/bin/bash", "-e", "-o", "pipefail", "-c"]

# Compile and install Node.js dependencies.
COPY ./plugin-server/package.json ./plugin-server/pnpm-lock.yaml ./plugin-server/tsconfig.json ./
COPY ./plugin-server/patches/ ./patches/
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
COPY ./plugin-server/src/ ./src/
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
FROM python:3.11.9-slim-bullseye AS posthog-build
WORKDIR /code
SHELL ["/bin/bash", "-e", "-o", "pipefail", "-c"]

# Compile and install Python dependencies.
# We install those dependencies on a custom folder that we will
# then copy to the last image.
COPY requirements.txt ./
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
    PIP_NO_BINARY=lxml,xmlsec pip install -r requirements.txt --compile --no-cache-dir --target=/python-runtime

ENV PATH=/python-runtime/bin:$PATH \
    PYTHONPATH=/python-runtime

# Add in Django deps and generate Django's static files.
COPY manage.py manage.py
COPY hogvm hogvm/
COPY posthog posthog/
COPY ee ee/
COPY --from=frontend-build /code/frontend/dist /code/frontend/dist
RUN SKIP_SERVICE_VERSION_REQUIREMENTS=1 STATIC_COLLECTION=1 DATABASE_URL='postgres:///' REDIS_URL='redis:///' python manage.py collectstatic --noinput


#
# ---------------------------------------------------------
#
FROM debian:bullseye-slim AS fetch-geoip-db
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
FROM unit:python3.11
WORKDIR /code
SHELL ["/bin/bash", "-e", "-o", "pipefail", "-c"]
ENV PYTHONUNBUFFERED 1

# Install OS runtime dependencies.
# Note: please add in this stage runtime dependences only!
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    "chromium" \
    "chromium-driver" \
    "libpq-dev" \
    "libxmlsec1" \
    "libxmlsec1-dev" \
    "libxml2" \
    "gettext-base"

# Install MS SQL dependencies
RUN curl https://packages.microsoft.com/keys/microsoft.asc | tee /etc/apt/trusted.gpg.d/microsoft.asc
RUN curl https://packages.microsoft.com/config/debian/11/prod.list | tee /etc/apt/sources.list.d/mssql-release.list
RUN apt-get update
RUN ACCEPT_EULA=Y apt-get install -y msodbcsql18

# Install NodeJS 18.
RUN apt-get install -y --no-install-recommends \
    "curl" \
    && \
    curl -fsSL https://deb.nodesource.com/setup_18.x | bash - && \
    apt-get install -y --no-install-recommends \
    "nodejs" \
    && \
    rm -rf /var/lib/apt/lists/*

# Install and use a non-root user.
RUN groupadd -g 1000 posthog && \
    useradd -r -g posthog posthog && \
    chown posthog:posthog /code
USER posthog

# Add the commit hash
ARG COMMIT_HASH
RUN echo $COMMIT_HASH > /code/commit.txt

# Add in the compiled plugin-server & its runtime dependencies from the plugin-server-build stage.
COPY --from=plugin-server-build --chown=posthog:posthog /code/plugin-server/dist /code/plugin-server/dist
COPY --from=plugin-server-build --chown=posthog:posthog /code/plugin-server/node_modules /code/plugin-server/node_modules
COPY --from=plugin-server-build --chown=posthog:posthog /code/plugin-server/package.json /code/plugin-server/package.json


# Copy the Python dependencies and Django staticfiles from the posthog-build stage.
COPY --from=posthog-build --chown=posthog:posthog /code/staticfiles /code/staticfiles
COPY --from=posthog-build --chown=posthog:posthog /python-runtime /python-runtime
ENV PATH=/python-runtime/bin:$PATH \
    PYTHONPATH=/python-runtime

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
COPY --chown=posthog:posthog hogvm hogvm/

# Keep server command backwards compatible
RUN cp ./bin/docker-server-unit ./bin/docker-server

# Setup ENV.
ENV NODE_ENV=production \
    CHROME_BIN=/usr/bin/chromium \
    CHROME_PATH=/usr/lib/chromium/ \
    CHROMEDRIVER_BIN=/usr/bin/chromedriver

# Expose container port and run entry point script.
EXPOSE 8000

# Expose the port from which we serve OpenMetrics data.
EXPOSE 8001
COPY unit.json.tpl /docker-entrypoint.d/unit.json.tpl
USER root
CMD ["./bin/docker"]