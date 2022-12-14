#
# This Dockerfile is used for self-hosted production builds.
#
# Note: for PostHog Cloud remember to update 'Dockerfile.cloud'
#       as appropriate.
#
# The first 3 stages are used to build:
#
# - static assets
# - plugin-server (Node.js app)
# - PostHog (Django app)
#
# while in the last and final stage we import the artifacts
# from the previous stages add some runtime dependencies
# and build the final image.
#

#
# ---------------------------------------------------------
#
FROM node:18.12.1-bullseye-slim AS frontend-build
WORKDIR /code
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

COPY package.json pnpm-lock.yaml ./
RUN corepack enable && \
    mkdir /tmp/pnpm-store && \
    pnpm install --frozen-lockfile --store-dir /tmp/pnpm-store && \
    rm -rf /tmp/pnpm-store

COPY frontend/ frontend/
COPY ./bin/ ./bin/
COPY babel.config.js tsconfig.json webpack.config.js ./
RUN pnpm build

#
# ---------------------------------------------------------
#
FROM node:18.12.1-bullseye-slim AS plugin-server-build
WORKDIR /code/plugin-server
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Compile and install pnpm dependencies.
COPY ./plugin-server/package.json ./plugin-server/pnpm-lock.yaml ./plugin-server/tsconfig.json ./
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    "make" \
    "g++" \
    "gcc" \
    "python3" \
    && rm -rf /var/lib/apt/lists/* && \
    corepack enable && \
    mkdir /tmp/pnpm-store && \
    pnpm install --frozen-lockfile --store-dir /tmp/pnpm-store && \
    rm -rf /tmp/pnpm-store

# Build the plugin server.
#
# Note: we run the build as a separate actions to increase
# the cache hit ratio of the layers above.
COPY ./plugin-server/src/ ./src/
RUN pnpm build

#
# ---------------------------------------------------------
#
FROM python:3.8.14-slim-bullseye AS posthog-build
WORKDIR /code
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Compile and install Python dependencies.
# We install those dependencies to a custom folder that we will
# then copy to the final image.
COPY requirements.txt ./
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    "build-essential" \
    "git" \
    "libpq-dev" \
    "libxmlsec1" \
    "libxmlsec1-dev" \
    "pkg-config" \
    && rm -rf /var/lib/apt/lists/* && \
    pip install -r requirements.txt --compile --no-cache-dir --target=/python-runtime

#
# ---------------------------------------------------------
#
FROM python:3.8.14-slim-bullseye
WORKDIR /code
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV PYTHONUNBUFFERED 1

# Install OS runtime dependencies.
#
# Note: please add in this section runtime dependences only.
# If you temporary need a package to build a Python or npm
# dependency take a look at the sections below.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    "chromium" \
    "chromium-driver" \
    "libpq-dev" \
    "libxmlsec1" \
    "libxmlsec1-dev" \
    "libxml2"

# Install NodeJS 18.
RUN apt-get install -y --no-install-recommends "curl" && \
    curl -fsSL https://deb.nodesource.com/setup_18.x | bash - && \
    apt-get install -y --no-install-recommends "nodejs"

# Add in the compiled plugin-server.
COPY --from=plugin-server-build /code/plugin-server/dist/ /code/plugin-server/dist/

# Fetch the GeoLite2-City database that will be used for IP geolocation within Django.
RUN apt-get install -y --no-install-recommends \
    "curl" \
    "brotli" \
    && \
    rm -rf /var/lib/apt/lists/* && \
    mkdir share && \
    ( curl -s -L "https://mmdbcdn.posthog.net/" | brotli --decompress --output=./share/GeoLite2-City.mmdb ) && \
    chmod -R 755 ./share/GeoLite2-City.mmdb

# Copy the Python dependencies from the posthog-build stage.
COPY --from=posthog-build /python-runtime /python-runtime
ENV PATH=/python-runtime/bin:$PATH
ENV PYTHONPATH=/python-runtime

# Add in Django deps and generate Django's static files.
COPY manage.py manage.py
COPY posthog posthog/
COPY ee ee/
COPY --from=frontend-build /code/frontend/dist /code/frontend/dist
RUN SKIP_SERVICE_VERSION_REQUIREMENTS=1 SECRET_KEY='unsafe secret key for collectstatic only' DATABASE_URL='postgres:///' REDIS_URL='redis:///' python manage.py collectstatic --noinput

# Add in Gunicorn config and custom bin files.
COPY gunicorn.config.py ./
COPY ./bin ./bin/

# Setup ENV.
ENV NODE_ENV=production \
    CHROME_BIN=/usr/bin/chromium \
    CHROME_PATH=/usr/lib/chromium/ \
    CHROMEDRIVER_BIN=/usr/bin/chromedriver

# Use a non-root user.
RUN groupadd posthog && \
    useradd -r -g posthog posthog && \
    chown posthog:posthog -R /code

USER posthog

# Expose container port and run entry point script.
EXPOSE 8000

# Expose the port from which we serve OpenMetrics data.
EXPOSE 8001

CMD ["./bin/docker"]
