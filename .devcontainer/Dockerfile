# Defines the environment you're dropped into with codespaces
# I've take
# https://github.com/microsoft/vscode-dev-containers/blob/main/containers/python-3/.devcontainer/Dockerfile
# and surrounding files as inspiration. I'm extending their image rather than
# building from e.g. the official python docker images as there appears to be
# quite a bit done as part of the vscode images, presumably to make the
# experience as rich as possible. Perhaps later down the line it might be worth
# rolling our own
#
# NOTE: I haven't tried to unify with `dev.Dockerfile` at this point. I want to
# understand what leaning into codespaces looks like first.
FROM mcr.microsoft.com/vscode/devcontainers/python:3.9-bullseye

# We might want to, e.g. install pip and node packages, but for now I'm just
# expecting to have to install these manually, for evaluation purposes.

ARG TARGETPLATFORM
ENV ARM64_PLATFORM=linux/arm64
WORKDIR /workspace

# Make sure all exit codes on pipes cause failures
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Add clickhouse deb repo
RUN [ "${TARGETPLATFORM}" != "${ARM64_PLATFORM}" ] \
    || apt-get -y install --no-install-recommends \
    "apt-transport-https=2.2.4" \
    "ca-certificates=20210119" \
    "dirmngr=2.2.27-2" \
    && curl -fsSL https://repo.clickhouse.com/CLICKHOUSE-KEY.GPG | gpg --dearmor > /etc/apt/trusted.gpg.d/clickhouse.gpg \
    && echo "deb [signed-by=/etc/apt/trusted.gpg.d/clickhouse.gpg] https://repo.clickhouse.com/deb/stable/ main/" > \
    /etc/apt/sources.list.d/clickhouse.list

# Add in some useful dev cli tools
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get -y install --no-install-recommends \
    # Add docker cli so we can do things like `docker logs`, and build images
    "docker.io=20.10.5+dfsg1-1+b5" \
    # Add in useful db debugging tools
    "postgresql-client=13+225" \
    # If we're on a supported platform, install the clickhouse cli
    "$([ "${TARGETPLATFORM}" = "${ARM64_PLATFORM}" ] || echo "clickhouse-client=21.11.4.14")" \
    && rm -rf /var/lib/apt/lists/*

# Install node
RUN curl -fsSL https://deb.nodesource.com/setup_14.x | bash - \
    && apt-get -y install --no-install-recommends "nodejs=14.18.1-deb-1nodesource1" \
    && rm -rf /var/lib/apt/lists/*

# NOTE: the below is mostly just a copy of /dev.Dockerfile

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
RUN pip install -r requirements-dev.txt --compile --no-cache-dir && \
    pip install -r requirements.txt --compile --no-cache-dir

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
RUN yarn config set network-timeout 300000 && \
    yarn install --frozen-lockfile \
    yarn cache clean

COPY ./plugin-server/package.json ./plugin-server/yarn.lock ./plugin-server/
RUN yarn config set network-timeout 300000 && \
    yarn install --frozen-lockfile \
    yarn cache clean