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
    build-essential \
    libpq-dev \
    libxml2-dev \
    libxmlsec1-dev \
    libxmlsec1-openssl \
    pkg-config \
    libssl-dev \
    libffi-dev \
    postgresql-client \
    netcat-openbsd \
    brotli \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# uv — Python package manager
COPY --from=ghcr.io/astral-sh/uv:0.10.12 /uv /usr/local/bin/uv

# mprocs — process manager used by bin/start
ARG MPROCS_VERSION=0.7.2
RUN ARCH=$(dpkg --print-architecture) && \
    case "${ARCH}" in amd64) MPROCS_ARCH='x86_64';; arm64) MPROCS_ARCH='aarch64';; *) echo "unsupported: ${ARCH}"; exit 1;; esac && \
    curl -fsSL "https://github.com/pvolok/mprocs/releases/download/v${MPROCS_VERSION}/mprocs-${MPROCS_VERSION}-linux-${MPROCS_ARCH}-musl.tar.gz" \
    | tar xz -C /usr/local/bin

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
