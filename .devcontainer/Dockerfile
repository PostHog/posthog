# PostHog Codespaces development environment
#
# Lean image — devcontainer features handle Rust, Go, gh CLI, sshd, and
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
    && rm -rf /var/lib/apt/lists/*

# uv — Python package manager
COPY --from=ghcr.io/astral-sh/uv:0.10 /uv /usr/local/bin/uv

# Node.js 24 via NodeSource
ARG NODE_MAJOR=24
ENV COREPACK_ENABLE_AUTO_PIN=0
ENV COREPACK_ENABLE_AUTO_PIN=0
RUN curl -fsSL https://deb.nodesource.com/setup_${NODE_MAJOR}.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && corepack enable \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspaces/posthog

# Pre-install Python dependencies (cached layer — rebuilds only when lockfile changes)
COPY pyproject.toml uv.lock ./
RUN uv sync

# Node dependencies are installed in on-create.sh (pnpm workspace
# requires the full source tree with all workspace package.json files)
