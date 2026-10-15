# PostHog Hobby Installer

A TUI (Terminal User Interface) and CI-compatible installer for PostHog self-hosted hobby deployments. Built with Go using [Bubbletea](https://github.com/charmbracelet/bubbletea).

## Features

- **Interactive TUI mode**: Beautiful terminal UI with spinners, colors, and step-by-step progress
- **CI mode**: Non-interactive mode for automated deployments (GitHub Actions, GitLab CI, etc.)
- Version picker (latest, latest-release, or custom tag/commit)
- Domain configuration with validation
- System requirement checks (Docker, memory, disk space, network)
- Step-by-step installation progress
- Health check waiting
- Success/failure screens with troubleshooting tips

## Usage

### Interactive mode (default)

```bash
./hobby-installer
```

### CI mode

CI mode is automatically enabled when common CI environment variables are detected (`CI`, `GITHUB_ACTIONS`, `GITLAB_CI`, etc.), or can be forced with `--ci`:

```bash
# Explicit CI mode
./hobby-installer --ci --domain posthog.example.com

# With specific version
./hobby-installer --ci --domain posthog.example.com --version latest

# Upgrade (domain read from existing .env)
./hobby-installer --ci
```

**Flags:**

- `--ci` - Force non-interactive CI mode
- `--domain` - Domain where PostHog will be accessible (required in CI mode unless already in `.env`)
- `--version` - PostHog version to install (default: `latest`)

## Building

### Prerequisites

- Go 1.25+

### Build commands

```bash
cd bin/hobby-installer

# Build for development (current arch) and run
make

# Build for specific architecture
make build-darwin
make build-linux

# Build all (development, linux, darwin)
make build-all
```

Output binaries:

- `bin/hobby-installer-linux` - Linux binary
- `bin/hobby-installer-darwin` - macOS binary (gitignored, local testing only)
- `bin/hobby-installer-development` - Development binary for current platform
- `bin/hobby-installer-demo` - Demo binary for testing UI components

### Running locally

```bash
# Build and run development binary
make run

# Or for macOS-specific binary
make build-darwin
../hobby-installer-darwin
```

### Demos

Run isolated demos of specific UI components:

```bash
# Build demo binary only
make build-demo

# Build and run a specific demo
make demo DEMO=checks
```

Available demos:

- `checks` - System requirements check UI

### Other make targets

```bash
make deps         # Download Go dependencies
make clean        # Remove build artifacts
make test         # Run Go tests
make fmt          # Format Go code
make lint         # Run golangci-lint
make help         # Show all available targets
```

## Architecture

```plaintext
bin/hobby-installer/
├── main.go        # Entry point: parses args, delegates to tui/ or ci/
├── core/          # Business logic (checks, install steps, docker, git, env)
├── tui/           # Interactive TUI mode (Bubbletea)
│   └── steps/     # Step views (welcome, version, domain, checks, install, complete)
├── ci/            # Non-interactive CI mode (console output)
├── ui/            # Shared UI components (styles, ASCII art)
└── demo/          # Demo binary for testing UI components
```

Both `tui/` and `ci/` consume the same `core.GetChecks()` and `core.GetInstallSteps()` - the logic is defined once, only the presentation differs.

## Installation flow

1. **Welcome** - Detect Install vs Upgrade mode
2. **Version** - Select PostHog version (latest recommended)
3. **Domain** - Enter domain for TLS certificate (skipped if already in `.env`)
4. **Checks** - Verify system requirements
5. **Install** - Clone repo, generate config, pull images, start Docker stack
6. **Complete** - Success message with URL or troubleshooting tips

## Compose files and overrides

Compose loads overrides differently for each install script. This does not make custom service settings a supported configuration.

- The installer runs `stop`, `down`, `pull`, and `up` with `-f docker-compose.yml`.
  Its migration check and database commands run without `-f`.
- `bin/deploy-hobby` runs `stop` and `up` with `-f docker-compose.yml`.
- The legacy `bin/upgrade-hobby` script runs `docker-compose` without `-f`.
  Commands without `-f` load `docker-compose.override.yml` automatically if it exists.
- All three scripts replace `docker-compose.yml` and `docker-compose.base.yml` on each run.
  Edits to these files do not persist. Keep local changes in a separate override file.

Commands with `-f docker-compose.yml` ignore that override file unless you add it explicitly.

To apply an override file, give it as a second `-f`:

```bash
docker-compose -f docker-compose.yml -f docker-compose.override.yml up -d
```

To see the configuration the installer uses, run:

```bash
docker-compose -f docker-compose.yml config
```

Add `-f docker-compose.override.yml` to the same command to see the merged result.

## Production deployment

On an Ubuntu server:

```bash
# Download and run
curl -L https://github.com/PostHog/posthog/releases/download/hobby-latest/posthog-hobby -o posthog-hobby
chmod +x posthog-hobby
./posthog-hobby
```

For CI/automated deployments:

```bash
curl -L https://github.com/PostHog/posthog/releases/download/hobby-latest/posthog-hobby -o posthog-hobby
chmod +x posthog-hobby
./posthog-hobby --ci --domain your-domain.com
```

## Release process

The hobby installer binary is automatically built and released when changes are pushed to `master` in the `bin/hobby-installer/` directory.

The GitHub workflow (`.github/workflows/build-hobby-installer.yml`) does the following:

1. Builds the Linux binary using `make build-linux`
2. Creates a versioned release (e.g., `hobby-20260108-153045`) for history
3. Updates the `hobby-latest` release with the new binary

This means:

- **Stable URL**: `https://github.com/PostHog/posthog/releases/download/hobby-latest/posthog-hobby` always points to the latest build
- **Version history**: All previous builds are available at `https://github.com/PostHog/posthog/releases?q=hobby-&expanded=true`
