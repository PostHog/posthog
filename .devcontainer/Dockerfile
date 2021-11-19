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

# Add clickhouse deb repo. Note that as of writing this repo doesn't have arm64
# debs so if you're e.g. on an M1 you'll have issues building this image
RUN [ "${TARGETPLATFORM}" != "${ARM64_PLATFORM}" ] \
    || apt-get install apt-transport-https ca-certificates dirmngr \
    && apt-key adv --keyserver hkp://keyserver.ubuntu.com:80 --recv E0C56BD4 \
    && echo "deb https://repo.clickhouse.com/deb/stable/ main/" | tee \
        /etc/apt/sources.list.d/clickhouse.list

RUN apt-get update \
    && apt-get install -y \
        # Add docker cli so we can do things like `docker logs`, and build images
        docker.io \
        # Add in useful db debugging tools
        postgresql-client \
        $([ "${TARGETPLATFORM}" = "${ARM64_PLATFORM}" ] || echo "clickhouse-client") \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deb.nodesource.com/setup_14.x | bash -

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
COPY ./plugin-server/ ./plugin-server/
RUN yarn config set network-timeout 300000 && \
    yarn install --frozen-lockfile && \
    yarn install --frozen-lockfile --cwd plugin-server && \
    yarn cache clean