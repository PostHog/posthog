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
FROM node:18.12.1-bullseye-slim AS frontend-build
WORKDIR /code
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

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
FROM node:18.12.1-bullseye-slim AS plugin-server-build
WORKDIR /code/plugin-server
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

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
# Build a version of the unit docker image for python3.10
# We can remove this step once we are on python3.11
FROM unit:python3.11 as unit
FROM python:3.10-bullseye as unit-131-python-310

# copied from https://github.com/nginx/unit/blob/master/pkg/docker/Dockerfile.python3.11
LABEL org.opencontainers.image.title="Unit (python3.10)"
LABEL org.opencontainers.image.description="Official build of Unit for Docker."
LABEL org.opencontainers.image.url="https://unit.nginx.org"
LABEL org.opencontainers.image.source="https://github.com/nginx/unit"
LABEL org.opencontainers.image.documentation="https://unit.nginx.org/installation/#docker-images"
LABEL org.opencontainers.image.vendor="NGINX Docker Maintainers <docker-maint@nginx.com>"
LABEL org.opencontainers.image.version="1.31.1"

RUN set -ex \
    && savedAptMark="$(apt-mark showmanual)" \
    && apt-get update \
    && apt-get install --no-install-recommends --no-install-suggests -y ca-certificates mercurial build-essential libssl-dev libpcre2-dev curl pkg-config \
    && mkdir -p /usr/lib/unit/modules /usr/lib/unit/debug-modules \
    && mkdir -p /usr/src/unit \
    && cd /usr/src/unit \
    && hg clone -u 1.31.1-1 https://hg.nginx.org/unit \
    && cd unit \
    && NCPU="$(getconf _NPROCESSORS_ONLN)" \
    && DEB_HOST_MULTIARCH="$(dpkg-architecture -q DEB_HOST_MULTIARCH)" \
    && CC_OPT="$(DEB_BUILD_MAINT_OPTIONS="hardening=+all,-pie" DEB_CFLAGS_MAINT_APPEND="-Wp,-D_FORTIFY_SOURCE=2 -fPIC" dpkg-buildflags --get CFLAGS)" \
    && LD_OPT="$(DEB_BUILD_MAINT_OPTIONS="hardening=+all,-pie" DEB_LDFLAGS_MAINT_APPEND="-Wl,--as-needed -pie" dpkg-buildflags --get LDFLAGS)" \
    && CONFIGURE_ARGS_MODULES="--prefix=/usr \
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
                --libdir=/usr/lib/$DEB_HOST_MULTIARCH" \
    && CONFIGURE_ARGS="$CONFIGURE_ARGS_MODULES \
                --njs" \
    && make -j $NCPU -C pkg/contrib .njs \
    && export PKG_CONFIG_PATH=$(pwd)/pkg/contrib/njs/build \
    && ./configure $CONFIGURE_ARGS --cc-opt="$CC_OPT" --ld-opt="$LD_OPT" --modulesdir=/usr/lib/unit/debug-modules --debug \
    && make -j $NCPU unitd \
    && install -pm755 build/sbin/unitd /usr/sbin/unitd-debug \
    && make clean \
    && ./configure $CONFIGURE_ARGS --cc-opt="$CC_OPT" --ld-opt="$LD_OPT" --modulesdir=/usr/lib/unit/modules \
    && make -j $NCPU unitd \
    && install -pm755 build/sbin/unitd /usr/sbin/unitd \
    && make clean \
    && /bin/true \
    && ./configure $CONFIGURE_ARGS_MODULES --cc-opt="$CC_OPT" --modulesdir=/usr/lib/unit/debug-modules --debug \
    && ./configure python --config=/usr/local/bin/python3-config \
    && make -j $NCPU python3-install \
    && make clean \
    && ./configure $CONFIGURE_ARGS_MODULES --cc-opt="$CC_OPT" --modulesdir=/usr/lib/unit/modules \
    && ./configure python --config=/usr/local/bin/python3-config \
    && make -j $NCPU python3-install \
    && cd \
    && rm -rf /usr/src/unit \
    && for f in /usr/sbin/unitd /usr/lib/unit/modules/*.unit.so; do \
        ldd $f | awk '/=>/{print $(NF-1)}' | while read n; do dpkg-query -S $n; done | sed 's/^\([^:]\+\):.*$/\1/' | sort | uniq >> /requirements.apt; \
       done \
    && apt-mark showmanual | xargs apt-mark auto > /dev/null \
    && { [ -z "$savedAptMark" ] || apt-mark manual $savedAptMark; } \
    && /bin/true \
    && mkdir -p /var/lib/unit/ \
    && mkdir -p /docker-entrypoint.d/ \
    && groupadd --gid 998 unit \
    && useradd \
         --uid 998 \
         --gid unit \
         --no-create-home \
         --home /nonexistent \
         --comment "unit user" \
         --shell /bin/false \
         unit \
    && apt-get update \
    && apt-get --no-install-recommends --no-install-suggests -y install curl $(cat /requirements.apt) \
    && apt-get purge -y --auto-remove build-essential \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /requirements.apt \
    && ln -sf /dev/stdout /var/log/unit.log

COPY --from=unit /usr/local/bin/docker-entrypoint.sh /usr/local/bin/
COPY --from=unit /usr/share/unit/welcome/welcome.* /usr/share/unit/welcome/

STOPSIGNAL SIGTERM

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
EXPOSE 80
CMD ["unitd", "--no-daemon", "--control", "unix:/var/run/control.unit.sock"]

#
# ---------------------------------------------------------
#
FROM unit-131-python-310
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
COPY unit.json /docker-entrypoint.d/unit.json
USER root
CMD ["./bin/docker "]
