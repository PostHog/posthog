# hadolint global ignore=DL3004

# hadolint doesn't like changes to this file, but it is only used for local dev

# Defines the environment you're dropped into with codespaces
# I've take
# https://github.com/microsoft/vscode-dev-containers/blob/main/containers/python-3/.devcontainer/Dockerfile
# and surrounding files as inspiration. I'm extending their image rather than
# building from e.g. the official python docker images as there appears to be
# quite a bit done as part of the vscode images, presumably to make the
# experience as rich as possible. Perhaps later down the line it might be worth
# rolling our own
#
FROM mcr.microsoft.com/vscode/devcontainers/python:3.11-bookworm

# Make sure all exit codes on pipes cause failures
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Set up docker in docker as per
# https://github.com/microsoft/vscode-dev-containers/blob/main/script-library/docs/docker-in-docker.md
COPY .devcontainer/library-scripts /tmp/library-scripts

ENV DOCKER_BUILDKIT=1
RUN /tmp/library-scripts/docker-in-docker-debian.sh
ENTRYPOINT ["/usr/local/share/docker-init.sh"]
VOLUME [ "/var/lib/docker" ]
CMD ["sleep", "infinity"]

# Add in some useful dev cli tools
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get -y install --no-install-recommends \
    # Add in useful db debugging tools
    "postgresql-client=15+*" \
    # needed for posthog to run
    netcat-openbsd brotli curl \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && sudo chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && sudo apt update \
    && sudo apt install gh -y

# Install node via NVM (https://github.com/nvm-sh/nvm)
ARG NODE_VERSION="18"
RUN if [ "${NODE_VERSION}" != "none" ]; then su vscode -c "umask 0002 && . /usr/local/share/nvm/nvm.sh && nvm install ${NODE_VERSION} 2>&1"; fi

# install pnpm globally, this container doesn't expose a supported shell to the pnpm installer
# so `RUN curl -fsSL https://get.pnpm.io/install.sh | sh -` fails
# see https://github.com/pnpm/pnpm/issues/4495
RUN corepack enable && pnpm --version \
    && SHELL=bash pnpm setup \
    && source /root/.bashrc

WORKDIR /workspace

# Compile and install Python dependencies.
#
# Notes:
#
# - we explicitly COPY the files so that we don't need to rebuild
#   the container every time a dependency changes
#
# - we need few additional OS packages for this. Let's install
#   and then uninstall them when the compilation is completed.
COPY pyproject.toml uv.lock ./
RUN --mount=from=ghcr.io/astral-sh/uv,source=/uv,target=/bin/uv \
    uv sync
