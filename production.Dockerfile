FROM python:3.8-slim
ENV PYTHONUNBUFFERED 1
RUN mkdir /code
WORKDIR /code

# to remove SAML deps either SAML_DISABLED env var or saml_disabled build arg can be set
ARG saml_disabled

COPY . /code/

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update \
    && apt-get install -y --no-install-recommends 'curl=7.*' 'git=1:2.*' 'build-essential=12.*' \
    && curl -sL https://deb.nodesource.com/setup_14.x | bash - \
    && apt-get install -y --no-install-recommends 'nodejs=14.*' \
    && npm install -g yarn@1 \
    && yarn config set network-timeout 300000 \
    && yarn --frozen-lockfile \
    && yarn build \
    && yarn --cwd plugins --frozen-lockfile --ignore-optional \
    && yarn cache clean \
    && rm -rf node_modules

# install dependencies but ignore any we don't need for dev environment
RUN pip install -r requirements.txt --no-cache-dir --compile

# install SAML dependencies (if available)
RUN if [[ -z "${SAML_DISABLED}" ]] && [[ -z "$saml_disabled" ]] ; then \
    apt-get install -y --no-install-recommends 'pkg-config=0.*' 'libxml2-dev=2.*' 'libxmlsec1-dev=1.*' 'libxmlsec1-openssl=1.*' && \
    pip install python3-saml==1.12.0 --no-cache-dir --compile && \
    apt-get purge -y pkg-config \
    ; fi


# uninstall unneeded dependencies
RUN pip uninstall ipython-genutils pip -y


# generate Django's static files
RUN SECRET_KEY='unsafe secret key for collectstatic only' DATABASE_URL='postgres:///' REDIS_URL='redis:///' python manage.py collectstatic --noinput

# remove build dependencies not needed at runtime
RUN rm -rf /var/lib/apt/lists/* \
    && apt-get purge -y git curl build-essential && apt-get autoremove -y

# add posthog user, move runtime files into home and change permissions
# this alleviates compliance issue for not running a container as root
RUN useradd -m posthog && mv /code /home/posthog && chown -R posthog:1000 /home/posthog/code

WORKDIR /home/posthog/code

USER posthog

EXPOSE 8000
CMD ["./bin/docker"]
