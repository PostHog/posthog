#
# This Dockerfile is used for self-hosted production builds.
#
# Note: for 'posthog/posthog-cloud' remember to update 'prod.web.Dockerfile' as appropriate
#
FROM python:3.8-alpine3.14

ENV PYTHONUNBUFFERED 1

WORKDIR /code

# To remove SAML dependencies either set 'saml_disabled' or 'SAML_DISABLED' build variables
ARG saml_disabled
ARG SAML_DISABLED

# Install OS dependencies needed to run PostHog
#
# Note: please add in this section runtime dependences only.
# If you temporary need a package to build a Python or npm
# dependency take a look at the sections below.
RUN apk --update --no-cache add \
    "bash~=5.1" \
    "g++~=10.3" \
    "gcc~=10.3" \
    "make~=4.3" \
    "nodejs~=14" \
    "libpq~=13.4" \
    "npm~=7" \
    && npm install -g yarn@1

# Install SAML dependencies (unless disabled)
#
# Note: please add in this section runtime dependences only.
# If you temporary need a package to build a Python or npm
# dependency take a look at the sections below.
RUN if [ -z "${SAML_DISABLED}" ] && [ -z "$saml_disabled" ] ; then \
    apk --update --no-cache add \
    "libxml2-dev~=2.9" \
    "libxslt~=1.1" \
    "libxslt-dev~=1.1" \
    "xmlsec~=1.2" \
    "xmlsec-dev~=1.2" \
    && \
    pip install python3-saml==1.12.0 --compile --no-cache-dir \
    ; fi

# Compile and install Python dependencies.
#
# Notes:
#
# - we need few additional OS packages for this. Let's install
#   and then uninstall them when the compilation is completed.
COPY requirements.txt ./
RUN apk --update --no-cache --virtual .build-deps add \
    "cargo~=1.52" \
    "git~=2" \
    "libffi-dev~=3.3" \
    "postgresql-dev~=13" \
    && \
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
COPY package.json yarn.lock plugins/package.json plugins/yarn.lock ./
RUN apk --update --no-cache --virtual .build-deps add \
    "gcc~=10.3" \
    && \
    yarn config set network-timeout 300000 && \
    yarn install --frozen-lockfile --ignore-optional && \
    yarn install --frozen-lockfile --ignore-optional --cwd plugins && \
    yarn cache clean \
    && \
    apk del .build-deps

# Copy everything else
COPY . .

# Build the frontend
#
# Note: we run the final install + build as a separate actions to increase
# the cache hit ratio of the layers above.
RUN yarn install --frozen-lockfile --ignore-optional && \
    yarn build && \
    yarn cache clean && \
    rm -rf node_modules

# Generate Django's static files
RUN SECRET_KEY='unsafe secret key for collectstatic only' DATABASE_URL='postgres:///' REDIS_URL='redis:///' python manage.py collectstatic --noinput

# Add a dedicated 'posthog' user and group, move files into its home dir and set the
# proper file permissions. This alleviates compliance issue for not running a
# container as 'root'
RUN addgroup -S posthog && \
    adduser -S posthog -G posthog && \
    mv /code /home/posthog && \
    chown -R posthog:1000 /home/posthog/code
WORKDIR /home/posthog/code
USER posthog

# Expose container port and run entry point script
EXPOSE 8000
CMD ["./bin/docker"]
