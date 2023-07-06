#
# This Dockerfile is used for self-hosted production builds.
#
# Note: for PostHog Cloud remember to update ‘Dockerfile.cloud’ as appropriate.
#
# The stages are used to:
#
# - frontend-build: build the frontend (static assets)
# - posthog-build: fetch PostHog (Django app) dependencies & build Django collectstatic
# - fetch-geoip-db: fetch the GeoIP database
#
# In the last stage, we import the artifacts from the previous
# stages, add some runtime dependencies and build the final image.
#


#
# ---------------------------------------------------------
#
FROM node:18.12.1-bullseye-slim AS frontend-build
WORKDIR /code
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

COPY package.json pnpm-lock.yaml ./
RUN corepack enable && pnpm --version && \
    mkdir /tmp/pnpm-store && \
    pnpm install --frozen-lockfile --store-dir /tmp/pnpm-store --prod && \
    rm -rf /tmp/pnpm-store

COPY frontend/ frontend/
COPY ./bin/ ./bin/
COPY babel.config.js tsconfig.json webpack.config.js ./
RUN pnpm build

#
# ---------------------------------------------------------
#
FROM python:3.10.10-slim-bullseye AS posthog-build
WORKDIR /code
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

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
    "pkg-config" \
    && \
    rm -rf /var/lib/apt/lists/* && \
    pip install -r requirements.txt --compile --no-cache-dir --target=/python-runtime

ENV PATH=/python-runtime/bin:$PATH \
    PYTHONPATH=/python-runtime

# Add in Django deps and generate Django's static files.
COPY manage.py manage.py
COPY posthog posthog/
COPY ee ee/
COPY --from=frontend-build /code/frontend/dist /code/frontend/dist
RUN SKIP_SERVICE_VERSION_REQUIREMENTS=1 SECRET_KEY='unsafe secret key for collectstatic only' DATABASE_URL='postgres:///' REDIS_URL='redis:///' python manage.py collectstatic --noinput


#
# ---------------------------------------------------------
#
FROM debian:bullseye-slim AS fetch-geoip-db
WORKDIR /code
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Fetch the GeoLite2-City database that will be used for IP geolocation within Django.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    "ca-certificates" \
    "curl" \
    "brotli" \
    && \
    rm -rf /var/lib/apt/lists/* && \
    mkdir share && \
    ( curl -s -L "https://mmdbcdn.posthog.net/" | brotli --decompress --output=./share/GeoLite2-City.mmdb ) && \
    chmod -R 755 ./share/GeoLite2-City.mmdb


#
# ---------------------------------------------------------
#
FROM python:3.10.10-slim-bullseye
WORKDIR /code
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
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
    "libxml2"

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
    useradd -u 999 -r -g posthog posthog && \
    chown posthog:posthog /code
USER posthog

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

# Setup ENV.
ENV NODE_ENV=production \
    CHROME_BIN=/usr/bin/chromium \
    CHROME_PATH=/usr/lib/chromium/ \
    CHROMEDRIVER_BIN=/usr/bin/chromedriver

# Expose container port and run entry point script.
EXPOSE 8000

# Expose the port from which we serve OpenMetrics data.
EXPOSE 8001

CMD ["./bin/docker"]
