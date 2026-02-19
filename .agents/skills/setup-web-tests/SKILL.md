---
name: setup-web-tests
description: Set up Python test environment in Claude Code for web where flox is unavailable. Use when you need to run backend tests and `uv sync` fails due to Python version mismatch.
---

# Claude Code for web — test setup

This document describes how to set up and run Python tests in a Claude Code for web environment, where flox is not available.

If you get stuck following these instructions, please bail out to the user and seek their guidance. Please suggest that they update this guide.

## Problem

The project requires a specific Python version pinned in `pyproject.toml` (check `requires-python`), but:

- Claude Code for web environments may have a different system Python version
- `uv python install <version>` may fail if the version isn't yet indexed by uv
- `uv sync` enforces the exact version constraint and will fail with the wrong Python version

## Solution: Download Python from python-build-standalone

Download the exact version from [python-build-standalone](https://github.com/astral-sh/python-build-standalone) GitHub releases. The script below auto-detects the required version from `pyproject.toml`:

```bash
# Auto-detect the required version from pyproject.toml
REQUIRED_VERSION=$(grep requires-python pyproject.toml | grep -oP '[\d.]+')
echo "Required Python: $REQUIRED_VERSION"

# Get the latest release tag from python-build-standalone
RELEASE_TAG=$(curl -sL "https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest" | grep '"tag_name"' | cut -d'"' -f4)

# Find and download the matching build
DOWNLOAD_URL=$(curl -sL "https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest" | \
  grep "browser_download_url" | grep "$REQUIRED_VERSION" | grep "x86_64-unknown-linux-gnu-install_only.tar.gz" | head -1 | cut -d'"' -f4)

mkdir -p /tmp/python-install && cd /tmp/python-install
curl -L -o python.tar.gz "$DOWNLOAD_URL"
tar -xzf python.tar.gz

# Verify
/tmp/python-install/python/bin/python3 --version
```

If the auto-detection doesn't find a URL (e.g., the version is too new), browse the [releases page](https://github.com/astral-sh/python-build-standalone/releases) manually and look for a `cpython-<version>+<tag>-x86_64-unknown-linux-gnu-install_only.tar.gz` asset.

### Install dependencies and run tests

```bash
cd /home/user/posthog
uv sync --python /tmp/python-install/python/bin/python3
source .venv/bin/activate

# Run a specific test
pytest path/to/test.py::TestClass::test_method -v

# Run all tests in a directory
pytest posthog/hogql/test/ -v
```

## Docker Services

Most tests require backend services running. If Docker is available, start them with:

```bash
docker compose -f docker-compose.dev.yml up -d
```

See `docker-compose.dev.yml` for the full list of services and ports. Some test directories have specific service requirements documented in their own configuration files.

### Hosts file setup

Tests expect certain hostnames to resolve to localhost:

```bash
echo "127.0.0.1 kafka clickhouse clickhouse-coordinator objectstorage" | sudo tee -a /etc/hosts
```

## Environment Variables

Tests require environment variables defined in [`.github/workflows/ci-backend.yml`](.github/workflows/ci-backend.yml) (see the `env:` section at the top of the file). You can also copy `.env.example` to `.env` for local development defaults.

## Additional Setup

### Frontend dist placeholders

Some tests require frontend build artifacts to exist (even if empty):

```bash
mkdir -p frontend/dist
touch frontend/dist/index.html
touch frontend/dist/layout.html
touch frontend/dist/exporter.html
```

### SAML dependencies (if needed)

For SAML-related functionality:

```bash
sudo apt-get update
sudo apt-get install libxml2-dev libxmlsec1-dev libxmlsec1-openssl
```

## Pytest Configuration

The `pytest.ini` sets:

- `pythonpath = . common`
- `DJANGO_SETTINGS_MODULE = posthog.settings`
- `DEBUG=1`, `TEST=1`

Default ignores: `--ignore=posthog/user_scripts --ignore=services/llm-gateway --ignore=common/ingestion/acceptance_tests`

## Debugging Installation Issues

If you encounter issues with the test setup, refer to [`.github/workflows/ci-backend.yml`](.github/workflows/ci-backend.yml) for the authoritative CI configuration. This file shows:

- Exact Python version used in CI
- System dependencies installed
- Environment variables set
- Docker services configuration
- Test execution commands

## Limitations

- **Docker unavailable**: Tests requiring services will fail without Docker
- **Network restrictions**: Downloading Python requires GitHub access
- **Temporal tests**: Require additional Temporal service setup
