# This Dockerfile is used for self-hosted production builds.
# Remember to update prod.web.Dockerfile for Cloud builds as appropriate.
FROM python:3.8-slim
ENV PYTHONUNBUFFERED 1
RUN mkdir /code
WORKDIR /code

# to remove SAML deps either SAML_DISABLED env var or saml_disabled build arg can be set
ARG saml_disabled
ARG SAML_DISABLED

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# install base dependencies, including node & yarn; remove unneeded build deps
RUN apt-get update \
    && apt-get install -y --no-install-recommends 'curl=7.*' 'git=1:2.*' 'build-essential=12.*' 'libpq-dev=13.*' \
    && curl -sL https://deb.nodesource.com/setup_14.x | bash - \
    && apt-get install -y --no-install-recommends 'nodejs=14.*' \
    && npm install -g yarn@1 \
    && yarn config set network-timeout 300000 \
    && rm -rf /var/lib/apt/lists/*


# install SAML dependencies (unless disabled)
RUN if [[ -z "${SAML_DISABLED}" ]] && [[ -z "$saml_disabled" ]] ; then \
    apt-get update \
    && apt-get install -y --no-install-recommends 'pkg-config=0.*' 'libxml2-dev=2.*' 'libxmlsec1-dev=1.*' 'libxmlsec1-openssl=1.*' \
    && pip install python3-saml==1.12.0 --no-cache-dir --compile \
    && apt-get purge -y pkg-config && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/* \
    ; fi


# install Python dependencies (production-level only)
COPY requirements.txt /code/.
RUN pip install -r requirements.txt --no-cache-dir --compile


# uninstall unneeded Python dependencies
RUN pip uninstall ipython-genutils pip wheel -y

# remove build dependencies not needed at runtime
RUN  apt-get purge -y git curl build-essential && apt-get autoremove -y

# install JS (yarn) dependencies
COPY package.json /code/.
COPY yarn.lock /code/.
RUN yarn --frozen-lockfile

# steps below will change on almost every build (steps above will be cached most of the time)
# load entire codebase & build frontend
COPY . /code/
RUN yarn build \
    && yarn --cwd plugins --frozen-lockfile --ignore-optional \
    && yarn cache clean \
    && rm -rf node_modules

# generate Django's static files
RUN SECRET_KEY='unsafe secret key for collectstatic only' DATABASE_URL='postgres:///' REDIS_URL='redis:///' python manage.py collectstatic --noinput

# add posthog user, move runtime files into home and change permissions
# this alleviates compliance issue for not running a container as root
RUN useradd -m posthog && mv /code /home/posthog && chown -R posthog:1000 /home/posthog/code
WORKDIR /home/posthog/code
USER posthog

# expose container port and run entry point script
EXPOSE 8000
CMD ["./bin/docker"]
