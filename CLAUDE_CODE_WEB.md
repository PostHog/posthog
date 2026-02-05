# Claude Code for Web - Test Setup

This document describes how to set up and run Python tests in a Claude Code for web environment, where flox is not available.

## Problem

The project requires Python 3.12.12 exactly (pinned in `pyproject.toml`), but:
- Claude Code for web environments typically have Python 3.12.3 (from system packages)
- `uv python install 3.12.12` may fail if the version isn't yet indexed by uv
- `uv sync` enforces the exact version constraint and will fail with the wrong Python version

## Solution: Download Python 3.12.12 from python-build-standalone

Python 3.12.12 is available from the [python-build-standalone](https://github.com/astral-sh/python-build-standalone) GitHub releases. Download and extract it, then use it with `uv sync`.

### Step 1: Download and install Python 3.12.12

```bash
# Create installation directory
mkdir -p /tmp/python-install && cd /tmp/python-install

# Download Python 3.12.12 from python-build-standalone
curl -L -o python-3.12.12.tar.gz \
  "https://github.com/astral-sh/python-build-standalone/releases/download/20260203/cpython-3.12.12%2B20260203-x86_64-unknown-linux-gnu-install_only.tar.gz"

# Extract
tar -xzf python-3.12.12.tar.gz

# Verify installation
/tmp/python-install/python/bin/python3.12 --version
# Should output: Python 3.12.12
```

### Step 2: Run uv sync with Python 3.12.12

```bash
cd /home/user/posthog
uv sync --python /tmp/python-install/python/bin/python3.12
```

This creates a `.venv` directory with all dependencies installed using the correct Python version.

### Step 3: Run tests

```bash
# Run a specific test
.venv/bin/pytest path/to/test.py::TestClass::test_method -v

# Run all tests in a directory
.venv/bin/pytest posthog/hogql/test/ -v
```

## Docker Services

Most tests require backend services running. If Docker is available:

```bash
docker compose -f docker-compose.dev.yml up -d
```

Key services for tests:
- **PostgreSQL** (port 5432): Django database
- **ClickHouse** (port 8123, 9000): Analytics database
- **Redis** (port 6379): Caching and Celery broker
- **Kafka** (port 9092): Event streaming
- **Zookeeper** (port 2181): Kafka coordination
- **Object Storage/MinIO** (port 19000): S3-compatible storage

Some test directories have specific service requirements documented in their own `cargo.yaml`, `package.json`, or similar configuration files.

### Hosts file setup

Tests expect certain hostnames to resolve to localhost:

```bash
echo "127.0.0.1 kafka clickhouse clickhouse-coordinator objectstorage" | sudo tee -a /etc/hosts
```

## Environment Variables

Tests expect certain environment variables. The CI uses these (from `.github/workflows/ci-backend.yml`):

```bash
export SECRET_KEY='6b01eee4f945ca25045b5aab440b953461faf08693a9abbf1166dc7c6b9772da'
export DATABASE_URL='postgres://posthog:posthog@localhost:5432/posthog'
export REDIS_URL='redis://localhost'
export CLICKHOUSE_HOST='localhost'
export CLICKHOUSE_SECURE='False'
export CLICKHOUSE_VERIFY='False'
export TEST=1
export DEBUG=1
export OBJECT_STORAGE_ENABLED='True'
export OBJECT_STORAGE_ENDPOINT='http://localhost:19000'
export OBJECT_STORAGE_ACCESS_KEY_ID='object_storage_root_user'
export OBJECT_STORAGE_SECRET_ACCESS_KEY='object_storage_root_password'
export DJANGO_SETTINGS_MODULE='posthog.settings'
```

You can also copy `.env.example` to `.env` for local development defaults.

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

## Limitations

- **Docker unavailable**: Tests requiring services will fail without Docker
- **Network restrictions**: Downloading Python requires GitHub access
- **Temporal tests**: Require additional Temporal service setup

## Quick Reference

```bash
# One-time Python setup
mkdir -p /tmp/python-install && cd /tmp/python-install
curl -L -o python-3.12.12.tar.gz \
  "https://github.com/astral-sh/python-build-standalone/releases/download/20260203/cpython-3.12.12%2B20260203-x86_64-unknown-linux-gnu-install_only.tar.gz"
tar -xzf python-3.12.12.tar.gz

# One-time project setup
cd /home/user/posthog
uv sync --python /tmp/python-install/python/bin/python3.12

# Create frontend placeholders
mkdir -p frontend/dist && touch frontend/dist/{index,layout,exporter}.html

# Set required environment variables
export SECRET_KEY='6b01eee4f945ca25045b5aab440b953461faf08693a9abbf1166dc7c6b9772da'
export DATABASE_URL='postgres://posthog:posthog@localhost:5432/posthog'
export REDIS_URL='redis://localhost'
export CLICKHOUSE_HOST='localhost'
export TEST=1
export DEBUG=1
export DJANGO_SETTINGS_MODULE='posthog.settings'

# Run a specific test
.venv/bin/pytest posthog/api/test/test_utils.py -v

# Run tests without services (unit tests only)
.venv/bin/pytest posthog/hogql/test/ -v
```

## Checking Docker availability

```bash
docker --version && docker compose version
```

If Docker is not available, you can only run unit tests that don't require external services. Many HogQL tests, for example, can run without services.

## Finding the correct Python release

If Python 3.12.12 is no longer available at the URL above (release tags change), find the latest release:

```bash
# Get the latest release tag
RELEASE_TAG=$(curl -sL "https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest" | grep '"tag_name"' | cut -d'"' -f4)

# Find the Python 3.12.12 download URL
curl -sL "https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest" | \
  grep "browser_download_url" | grep "3.12.12" | grep "x86_64-unknown-linux-gnu-install_only.tar.gz"
```
