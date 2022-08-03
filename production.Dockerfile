#
# This Dockerfile is used for self-hosted production builds.
#
# Note: for 'posthog/posthog-cloud' remember to update 'prod.web.Dockerfile' as appropriate
#

#
# Build the frontend artifacts
#
FROM node:16.15-alpine3.14 AS frontend

WORKDIR /code

COPY package.json yarn.lock ./
RUN yarn config set network-timeout 300000 && \
    yarn install --frozen-lockfile

COPY frontend/ frontend/
COPY ./bin/ ./bin/
COPY babel.config.js tsconfig.json webpack.config.js ./
RUN yarn build

#
# Build the plugin-server artifacts. Note that we still need to install the
# runtime deps in the main image
#
FROM node:16.15-alpine3.14 AS plugin-server

WORKDIR /code/plugin-server

# Install python, make and gcc as they are needed for the yarn install
RUN apk --update --no-cache add \
    "make~=4.3" \
    "g++~=10.3" \
    "gcc~=10.3" \
    "python3~=3.9"

# Compile and install Yarn dependencies.
#
# Notes:
#
# - we explicitly COPY the files so that we don't need to rebuild
#   the container every time a dependency changes
COPY ./plugin-server/package.json ./plugin-server/yarn.lock ./plugin-server/tsconfig.json ./
RUN yarn config set network-timeout 300000 && \
    yarn install

# Build the plugin server
#
# Note: we run the build as a separate actions to increase
# the cache hit ratio of the layers above.
COPY ./plugin-server/src/ ./src/
RUN yarn build

# Build the posthog image, incorporating the Django app along with the frontend,
# as well as the plugin-server
FROM python:3.8.12-alpine3.14

ENV PYTHONUNBUFFERED 1

WORKDIR /code

# Install OS dependencies needed to run PostHog
#
# Note: please add in this section runtime dependences only.
# If you temporary need a package to build a Python or npm
# dependency take a look at the sections below.
RUN apk --update --no-cache add \
    "libpq~=13" \
    "libxslt~=1.1" \
    "nodejs-current~=16" \
    "chromium~=93" \
    "chromium-chromedriver~=93" \
    "xmlsec~=1.2"

# Curl the GeoLite2-City database that will be used for IP geolocation within Django 
#
# Notes:
#
# - We are doing this here because it makes sense to ensure the stack will work
#   even if the database is not available at the time of boot.
#   It's better here to fail at build then it is to fail at boot time.

RUN apk --update --no-cache --virtual .geolite-deps add \
    "curl~=7" \
    "brotli~=1.0.9" \
    && \
    mkdir share \
    && \
    ( curl -L "https://mmdbcdn.posthog.net/" | brotli --decompress --output=./share/GeoLite2-City.mmdb ) \
    && \
    chmod -R 755 ./share/GeoLite2-City.mmdb \
    && \
    apk del .geolite-deps


# Compile and install Python dependencies.
#
# Notes:
#
# - we explicitly COPY the files so that we don't need to rebuild
#   the container every time a dependency changes
#
# - we need few additional OS packages for this. Let's install
#   and then uninstall them when the compilation is completed.
COPY requirements.txt ./
RUN apk --update --no-cache --virtual .build-deps add \
    "bash~=5.1" \
    "g++~=10.3" \
    "gcc~=10.3" \
    "cargo~=1.52" \
    "git~=2" \
    "make~=4.3" \
    "libffi-dev~=3.3" \
    "libxml2-dev~=2.9" \
    "libxslt-dev~=1.1" \
    "xmlsec-dev~=1.2" \
    "postgresql-dev~=13" \
    "libmaxminddb~=1.5" \
    && \
    pip install -r requirements.txt --compile --no-cache-dir \
    && \
    apk del .build-deps

RUN addgroup -S posthog && \
    adduser -S posthog -G posthog

RUN chown posthog.posthog /code

USER posthog

# Add in Django deps and generate Django's static files
COPY manage.py manage.py
COPY posthog posthog/
COPY ee ee/
COPY --from=frontend /code/frontend/dist /code/frontend/dist

RUN SKIP_SERVICE_VERSION_REQUIREMENTS=1 SECRET_KEY='unsafe secret key for collectstatic only' DATABASE_URL='postgres:///' REDIS_URL='redis:///' python manage.py collectstatic --noinput

# Add in the plugin-server compiled code, as well as the runtime dependencies
WORKDIR /code/plugin-server
COPY ./plugin-server/package.json ./plugin-server/yarn.lock ./

# Switch to root and install yarn so we can install runtime deps. Node that we
# still need yarn to run the plugin-server so we do not remove it.
USER root
RUN apk --update --no-cache add "yarn~=1"

# NOTE: we need make and g++ for node-gyp
# NOTE: npm is required for re2
RUN apk --update --no-cache add "make~=4.3" "g++~=10.3" "npm~=7" --virtual .build-deps \
    && yarn install --frozen-lockfile --production=true \
    && yarn cache clean \
    && apk del .build-deps

USER posthog

# Add in the compiled plugin-server
COPY --from=plugin-server /code/plugin-server/dist/ ./dist/

WORKDIR /code/
USER root
COPY ./plugin-server/package.json ./plugin-server/

# We need bash to run the bin scripts
RUN apk --update --no-cache add "bash~=5.1"
COPY ./bin ./bin/
USER posthog

ENV CHROME_BIN=/usr/bin/chromium-browser \
    CHROME_PATH=/usr/lib/chromium/ \
    CHROMEDRIVER_BIN=/usr/bin/chromedriver

COPY gunicorn.config.py ./

# Expose container port and run entry point script
EXPOSE 8000

# Expose the port from which we serve OpenMetrics data
EXPOSE 8001

CMD ["./bin/docker"]
