# Defines the environment you're dropped into with codespaces
# I've take
# https://github.com/microsoft/vscode-dev-containers/blob/main/containers/python-3/.devcontainer/Dockerfile
# and surrounding files as inspiration. I'm extending their image rather than
# building from e.g. the official python docker images as there appears to be
# quite a bit done as part of the vscode images, presumably to make the
# experience as rich as possible. Perhaps later down the line it might be worth
# rolling our own
#
FROM mcr.microsoft.com/vscode/devcontainers/python:3.10-bullseye

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
    "postgresql-client=13+*" \
    && rm -rf /var/lib/apt/lists/*

# Install node via NVM (https://github.com/nvm-sh/nvm)
ARG NODE_VERSION="18"
RUN if [ "${NODE_VERSION}" != "none" ]; then su vscode -c "umask 0002 && . /usr/local/share/nvm/nvm.sh && nvm install ${NODE_VERSION} 2>&1"; fi

RUN curl -fsSL https://get.pnpm.io/install.sh | sh -

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
COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements-dev.txt --compile --no-cache-dir && \
    pip install -r requirements.txt --compile --no-cache-dir
