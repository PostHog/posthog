#
# This Dockerfile is used for self-hosted development builds.
#
# Note: for 'posthog/posthog-cloud' remember to update 'dev.Dockerfile' as appropriate
#
FROM python:3.8.12-alpine3.14

ENV PYTHONUNBUFFERED 1
ENV DEBUG 1

WORKDIR /code

# Install OS dependencies needed to run PostHog
#
# Note: please add in this section runtime dependences only.
# If you temporary need a package to build a Python or npm
# dependency take a look at the sections below.
RUN apk --update --no-cache add \
    "bash~=5.1" \
    "g++~=10.3" \
    "gcc~=10.3" \
    "libpq~=13" \
    "libxml2-dev~=2.9" \
    "libxslt~=1.1" \
    "libxslt-dev~=1.1" \
    "xmlsec~=1.2" \
    "make~=4.3" \
    "nodejs-current~=16" \
    "npm~=7" \
    "chromium~=93" \
    "chromium-chromedriver~=93" \
    && npm install -g yarn@1

# Compile and install Python dependencies.
#
# Notes:
#
# - we explicitly COPY the files so that we don't need to rebuild
#   the container every time a dependency changes
#
# - we need few additional OS packages for this. Let's install
#   and then uninstall them when the compilation is completed.
# `libxml2-dev`, `xmlsec` & `xmlsec-dev` are dependencies for python3-saml
COPY requirements.txt requirements-dev.txt ./
RUN apk --update --no-cache --virtual .build-deps add \
    "cargo~=1.52" \
    "git~=2" \
    "libffi-dev~=3.3" \
    "linux-headers~=5.10" \
    "musl-dev~=1.2" \
    "openssl-dev~=1.1" \
    "postgresql-dev~=13" \
    "libxml2-dev~=2.9" \
    "xmlsec-dev~=1.2" \
    && \
    pip install -r requirements-dev.txt --compile --no-cache-dir && \
    pip install -r requirements.txt --compile --no-cache-dir \
    && \
    apk del .build-deps

# Compile and install Yarn dependencies.
#
# Notes:
#
# - we explicitly COPY the files so that we don't need to rebuild
#   the container every time a dependency changes
#
# - we need few additional OS packages for this. Let's install
#   and then uninstall them when the compilation is completed.
COPY package.json yarn.lock ./
COPY ./plugin-server/ ./plugin-server/
RUN apk --update --no-cache --virtual .build-deps add \
    "gcc~=10.3" \
    && \
    yarn config set network-timeout 300000 && \
    yarn install --frozen-lockfile && \
    yarn install --frozen-lockfile --cwd plugin-server && \
    yarn cache clean \
    && \
    apk del .build-deps

# Copy everything else
COPY . .

# Generate Django's static files
RUN mkdir -p frontend/dist && \
    DATABASE_URL='postgres:///' REDIS_URL='redis:///' python manage.py collectstatic --noinput

# Expose container port and run entry point script
EXPOSE 8000
EXPOSE 8234

ENV CHROME_BIN=/usr/bin/chromium-browser \
    CHROME_PATH=/usr/lib/chromium/ \
    CHROMEDRIVER_BIN=/usr/bin/chromedriver

CMD ["./bin/docker-dev"]
