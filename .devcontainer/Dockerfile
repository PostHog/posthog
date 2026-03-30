# PostHog Codespaces development environment
#
# Lean image — devcontainer features handle Rust, gh CLI, sshd, and
# Docker-in-Docker. This Dockerfile installs system deps, uv, Node, and
# pre-installs Python + JS dependencies for faster startup.

FROM mcr.microsoft.com/devcontainers/base:ubuntu-22.04

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV DEBIAN_FRONTEND=noninteractive

# System packages required by PostHog Python deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential=12.9ubuntu3 \
    libpq-dev=14.22-0ubuntu0.22.04.1 \
    libxml2-dev=2.9.13+dfsg-1ubuntu0.11 \
    libxmlsec1-dev=1.2.33-1build2 \
    libxmlsec1-openssl=1.2.33-1build2 \
    pkg-config=0.29.2-1ubuntu3 \
    libssl-dev=3.0.2-0ubuntu1.21 \
    libffi-dev=3.4.2-4 \
    postgresql-client=14+238 \
    netcat-openbsd=1.218-4ubuntu1 \
    brotli=1.0.9-2build6 \
    curl=7.81.0-1ubuntu1.23 \
    unzip=6.0-26ubuntu3.2 \
    && rm -rf /var/lib/apt/lists/*

# uv — Python package manager
COPY --from=ghcr.io/astral-sh/uv:0.10.12 /uv /usr/local/bin/uv

# phrocs — process manager used by bin/start
RUN ARCH=$(dpkg --print-architecture) && \
    curl -fsSL "https://github.com/PostHog/posthog/releases/download/phrocs-latest/phrocs-linux-${ARCH}" \
    -o /usr/local/bin/phrocs && chmod +x /usr/local/bin/phrocs

# Node.js via tarball (avoids a second apt-get update cycle from NodeSource)
ARG NODE_VERSION=24.14.0
ENV COREPACK_ENABLE_AUTO_PIN=0
RUN ARCH=$(dpkg --print-architecture) && \
    case "${ARCH}" in amd64) NODE_ARCH='x64';; arm64) NODE_ARCH='arm64';; *) echo "unsupported: ${ARCH}"; exit 1;; esac && \
    curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz" \
    | tar xJ -C /usr/local --strip-components=1 --no-same-owner \
    && corepack enable

# rpk — Kafka topic management (pre-create topics before services start)
RUN ARCH=$(dpkg --print-architecture) && \
    curl -fsSL "https://github.com/redpanda-data/redpanda/releases/download/v25.1.9/rpk-linux-${ARCH}.zip" \
    -o /tmp/rpk.zip && unzip -o /tmp/rpk.zip -d /usr/local/bin/ rpk && rm /tmp/rpk.zip

WORKDIR /workspaces/posthog

# Pre-install Python dependencies (cached layer — rebuilds only when lockfile changes)
COPY pyproject.toml uv.lock ./
RUN uv sync

# Node dependencies are installed in on-create.sh (pnpm workspace
# requires the full source tree with all workspace package.json files)
