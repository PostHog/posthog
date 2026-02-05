# Claude Code for Web - Test Setup

This document describes how to set up and run Python tests in a Claude Code for web environment, where flox is not available.

If you get stuck following these instructions, please bail out to the user and seek their guidance. Please suggest that they update this guide.

## Problem

The project requires a specific Python version pinned in `pyproject.toml` (check `requires-python`), but:
- Claude Code for web environments may have a different system Python version
- `uv python install <version>` may fail if the version isn't yet indexed by uv
- `uv sync` enforces the exact version constraint and will fail with the wrong Python version

## Solution: Download Python from python-build-standalone

First, check the required Python version:

```bash
grep requires-python pyproject.toml
# Example output: requires-python = "==3.12.12"
```

Then download the exact version from [python-build-standalone](https://github.com/astral-sh/python-build-standalone) GitHub releases.

### Example: Installing Python 3.12.12

The following example shows how to install Python 3.12.12. Adjust the version numbers as needed for your `pyproject.toml` requirements.

#### Step 1: Download and install Python

```bash
# Create installation directory
mkdir -p /tmp/python-install && cd /tmp/python-install

# Download Python 3.12.12 from python-build-standalone
# Note: This URL is an example. Replace the version and <RELEASE_TAG> with a valid release from GitHub Releases.
curl -L -o python.tar.gz \
  "https://github.com/astral-sh/python-build-standalone/releases/download/<RELEASE_TAG>/cpython-3.12.12%2B<RELEASE_TAG>-x86_64-unknown-linux-gnu-install_only.tar.gz"

# Extract
tar -xzf python.tar.gz

# Verify installation
/tmp/python-install/python/bin/python3.12 --version
# Should output: Python 3.12.12
```

#### Step 2: Run uv sync with the installed Python

```bash
cd /home/user/posthog
uv sync --python /tmp/python-install/python/bin/python3.12
```

This creates a `.venv` directory with all dependencies installed using the correct Python version.

#### Step 3: Activate the venv and run tests

```bash
# Activate the virtual environment
source .venv/bin/activate

# Run a specific test
pytest path/to/test.py::TestClass::test_method -v

# Run all tests in a directory
pytest posthog/hogql/test/ -v
```

### Finding the correct download URL

If you need a different Python version or the release tag has changed:

```bash
# Get the latest release tag
RELEASE_TAG=$(curl -sL "https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest" | grep '"tag_name"' | cut -d'"' -f4)
echo "Latest release: $RELEASE_TAG"

# Find the download URL for your version (replace X.Y.Z with your version)
curl -sL "https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest" | \
  grep "browser_download_url" | grep "3.12.12" | grep "x86_64-unknown-linux-gnu-install_only.tar.gz"
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

## Quick Reference

```bash
# Check required Python version
grep requires-python pyproject.toml

# One-time Python setup (example for 3.12.12)
mkdir -p /tmp/python-install && cd /tmp/python-install
curl -L -o python.tar.gz \
  "https://github.com/astral-sh/python-build-standalone/releases/download/20260203/cpython-3.12.12%2B20260203-x86_64-unknown-linux-gnu-install_only.tar.gz"
tar -xzf python.tar.gz

# One-time project setup
cd /home/user/posthog
uv sync --python /tmp/python-install/python/bin/python3.12

# Create frontend placeholders
mkdir -p frontend/dist && touch frontend/dist/{index,layout,exporter}.html

# Set environment variables (see .github/workflows/ci-backend.yml for full list)
cp .env.example .env

# Activate the virtual environment
source .venv/bin/activate

# Run a specific test
pytest posthog/api/test/test_utils.py -v

# Run tests without services (unit tests only)
pytest posthog/hogql/test/ -v
```

## Checking Docker availability

```bash
docker --version && docker compose version
```

If Docker is not available, you can only run unit tests that don't require external services. Many HogQL tests, for example, can run without services.
