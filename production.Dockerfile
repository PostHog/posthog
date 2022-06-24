#
# This Dockerfile is used for self-hosted production builds.
#
# Note: for 'posthog/posthog-cloud' remember to update 'prod.web.Dockerfile' as appropriate
#
FROM python:3.8.12-alpine3.14

ENV PYTHONUNBUFFERED 1

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
    "make~=4.3" \
    "nodejs-current~=16" \
    "npm~=7" \
    "chromium~=93" \
    "chromium-chromedriver~=93" \
    && npm install -g yarn@1

# Install SAML dependencies
RUN apk --update --no-cache add \
    "libxml2-dev~=2.9" \
    "xmlsec~=1.2" \
    "xmlsec-dev~=1.2"

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
    "cargo~=1.52" \
    "git~=2" \
    "libffi-dev~=3.3" \
    "postgresql-dev~=13" \
    && \
    pip install -r requirements.txt --compile --no-cache-dir \
    && \
    apk del .build-deps

# Copy everything else
COPY . .

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
RUN apk --update --no-cache --virtual .build-deps add \
    "gcc~=10.3" \
    && \
    yarn config set network-timeout 300000 && \
    yarn install --frozen-lockfile && \
    yarn build && \
    yarn cache clean && \
    rm -rf ./node_modules &&\
    yarn install --frozen-lockfile --cwd plugin-server && \
    yarn cache clean && \
    apk del .build-deps



# Build the plugin server
#
# Note: we run the build as a separate actions to increase
# the cache hit ratio of the layers above.
# symlink musl -> ld-linux is required for re2 compat on alpine
RUN cd plugin-server \
    && ln -s /lib/ld-musl-x86_64.so.1 /lib/ld-linux-x86-64.so.2 \
    && yarn build \
    && yarn cache clean \
    && cd ..

# Generate Django's static files
RUN SKIP_SERVICE_VERSION_REQUIREMENTS=1 SECRET_KEY='unsafe secret key for collectstatic only' DATABASE_URL='postgres:///' REDIS_URL='redis:///' python manage.py collectstatic --noinput

# Add a dedicated 'posthog' user and group, move files into its home dir and set the
# proper file permissions. This alleviates compliance issue for not running a
# container as 'root'
RUN addgroup -S posthog && \
    adduser -S posthog -G posthog && \
    mv /code /home/posthog && \
    chown -R posthog:1000 /home/posthog/code
WORKDIR /home/posthog/code
USER posthog

ENV CHROME_BIN=/usr/bin/chromium-browser \
    CHROME_PATH=/usr/lib/chromium/ \
    CHROMEDRIVER_BIN=/usr/bin/chromedriver

# Expose container port and run entry point script
EXPOSE 8000
CMD ["./bin/docker"]
