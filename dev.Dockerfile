FROM python:3.8-alpine3.14

ENV PYTHONUNBUFFERED 1
ENV DEBUG 1

WORKDIR /code

COPY . .

# Install OS dependencies needed to run PostHog
RUN apk --update --no-cache add \
    "nodejs~=14" \
    "npm~=7" \
    "postgresql-client~=13" \
    "libxslt~=1.1" \
    "libxslt-dev~=1.1" \
    "libxml2-dev~=2.9" \
    && npm install -g yarn@1 \
    && yarn config set network-timeout 300000 \
    && yarn --frozen-lockfile

# Compile and install Python dependencies.
# Note: we need few additional OS packages for this. Let's install
# and then uninstall them when the compilation is completed.
RUN apk --update --no-cache --virtual .build-deps add \
    "linux-headers~=5.10" \
    "musl-dev~=1.2" \
    "gcc~=10.3" \
    "g++~=10.3" \
    "git~=2" \
    "make~=4.3" \
    "libffi-dev~=3.3" \
    "postgresql-dev~=13" \
    "openssl-dev~=1.1" \
    "cargo~=1.52" \
    && \
    pip install -r requirements-dev.txt --compile --no-cache-dir && \
    pip install -r requirements.txt --no-cache-dir \
    && \
    apk del .build-deps

# Generate Django's static files
RUN mkdir -p frontend/dist && \
    DATABASE_URL='postgres:///' REDIS_URL='redis:///' python manage.py collectstatic --noinput

# Compile and install frontend dependencies.
# Note: like above, we need few additional OS packages for this. Let's
# install and then uninstall them when the compilation is completed.
RUN apk --update --no-cache --virtual .build-deps add \
    "gcc~=10.3" \
    "g++~=10.3" \
    "make~=4.3" \
    && \
    yarn install && \
    yarn install --cwd plugins && \
    yarn cache clean \
    && \
    apk del .build-deps

# Expose container port and run entry point script
EXPOSE 8000
EXPOSE 8234
CMD ["./bin/docker-dev"]
