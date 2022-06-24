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

# Install python and make as they are needed for the yarn install
RUN apk --update --no-cache add "python3" "make~=4.3"

# Compile and install Yarn dependencies.
#
# Notes:
#
# - we explicitly COPY the files so that we don't need to rebuild
#   the container every time a dependency changes
COPY ./plugin-server/package.json yarn.lock ./
RUN yarn config set network-timeout 300000 && \
    yarn install

# Build the plugin server
#
# Note: we run the build as a separate actions to increase
# the cache hit ratio of the layers above.
# symlink musl -> ld-linux is required for re2 compat on alpine
RUN yarn build

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
    "chromium-chromedriver~=93"

# Install SAML runtime dependencies
RUN apk --update --no-cache add "xmlsec~=1.2"

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
COPY package.json yarn.lock ./

# Switch to root and install yarn so we can install runtime deps. Node that we
# still need yarn to run the plugin-server so we do not remove it.
USER root
RUN apk --update --no-cache add "yarn~=1"
USER posthog
RUN yarn install --frozen-lockfile --production=true

# Add in the compiled plugin-server
COPY --from=plugin-server /code/plugin-server/dist/ ./dist/

ENV CHROME_BIN=/usr/bin/chromium-browser \
    CHROME_PATH=/usr/lib/chromium/ \
    CHROMEDRIVER_BIN=/usr/bin/chromedriver

# Expose container port and run entry point script
EXPOSE 8000
CMD ["./bin/docker"]
