#
# This Dockerfile is used for self-hosted development builds.
#
# Note: for 'posthog/posthog-cloud' remember to update 'dev.Dockerfile' as appropriate
#
FROM python:3.8-alpine3.14

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
    "libpq~=13.4" \
    "libxml2-dev~=2.9" \
    "libxslt~=1.1" \
    "libxslt-dev~=1.1" \
    "make~=4.3" \
    "nodejs~=14" \
    "npm~=7" \
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
COPY requirements.txt requirements-dev.txt ./
RUN apk --update --no-cache --virtual .build-deps add \
    "cargo~=1.52" \
    "git~=2" \
    "libffi-dev~=3.3" \
    "linux-headers~=5.10" \
    "musl-dev~=1.2" \
    "openssl-dev~=1.1" \
    "postgresql-dev~=13" \
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
COPY plugins/package.json plugins/yarn.lock ./plugins/
RUN apk --update --no-cache --virtual .build-deps add \
    "gcc~=10.3" \
    && \
    yarn config set network-timeout 300000 && \
    yarn install --frozen-lockfile && \
    yarn install --frozen-lockfile --cwd plugins && \
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
CMD ["./bin/docker-dev"]
