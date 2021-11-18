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

# Add clickhouse deb repo. Note that as of writing this repo doesn't have arm64
# debs so if you're e.g. on an M1 you'll have issues building this image
RUN apt-get install apt-transport-https ca-certificates dirmngr
RUN apt-key adv --keyserver hkp://keyserver.ubuntu.com:80 --recv E0C56BD4
RUN echo "deb https://repo.clickhouse.com/deb/stable/ main/" | tee \
        /etc/apt/sources.list.d/clickhouse.list

RUN apt-get update \
    && apt-get install -y \
        # Add docker cli so we can do things like `docker logs`, and build images
        docker.io \
        # Add in useful db debugging tools
        postgresql-client \
        clickhouse-client \
    && rm -rf /var/lib/apt/lists/*

