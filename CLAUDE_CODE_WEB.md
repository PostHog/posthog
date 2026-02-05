# Claude Code for Web - Test Setup

This document describes how to set up and run Python tests in a Claude Code for web environment, where flox is not available and Python 3.12.12 cannot be easily downloaded.

## Problem

The project requires Python 3.12.12 exactly (pinned in `pyproject.toml`), but:
- Claude Code for web environments typically have Python 3.12.3 (from system packages)
- Python 3.12.12 is not available in python-build-standalone (used by `uv`)
- External downloads may be restricted
- `uv sync` enforces the exact version constraint and will fail

## Solution

Use `uv pip install` instead of `uv sync` to install dependencies into a manually created virtualenv. This bypasses the `requires-python` version check.

### Step 1: Create a virtualenv with system Python

```bash
/usr/bin/python3.12 -m venv /tmp/posthog-venv
```

### Step 2: Install dependencies using uv pip

```bash
# Install main dependencies
uv pip install -p /tmp/posthog-venv --requirements /home/user/posthog/pyproject.toml

# Install dev dependencies (includes pytest, etc.)
uv pip install -p /tmp/posthog-venv --group dev --requirements /home/user/posthog/pyproject.toml
```

### Step 3: Run tests

```bash
# Set PYTHONPATH and use the virtualenv's pytest
PYTHONPATH=/home/user/posthog:/home/user/posthog/common \
  /tmp/posthog-venv/bin/pytest path/to/test.py::TestClass::test_method
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

- **Python 3.12.3 vs 3.12.12**: Minor version difference, most tests should work
- **Docker unavailable**: Tests requiring services will fail without Docker
- **Network restrictions**: Some tests may fail in restricted environments
- **Temporal tests**: Require additional Temporal service setup

## Quick Reference

```bash
# One-time setup
/usr/bin/python3.12 -m venv /tmp/posthog-venv
uv pip install -p /tmp/posthog-venv --requirements pyproject.toml
uv pip install -p /tmp/posthog-venv --group dev --requirements pyproject.toml

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
PYTHONPATH=.:/home/user/posthog/common /tmp/posthog-venv/bin/pytest posthog/api/test/test_utils.py -v

# Run tests without services (unit tests only)
PYTHONPATH=.:/home/user/posthog/common /tmp/posthog-venv/bin/pytest posthog/hogql/test/ -v
```

## Checking Docker availability

```bash
docker --version && docker compose version
```

If Docker is not available, you can only run unit tests that don't require external services. Many HogQL tests, for example, can run without services.
