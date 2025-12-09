# PostHog Hobby Installer

An interactive TUI (Terminal User Interface) installer for PostHog self-hosted hobby deployments. Built with Go using [Bubbletea](https://github.com/charmbracelet/bubbletea).

## Features

- Interactive welcome screen with Install/Upgrade mode selection
- Version picker (latest, latest-release, or custom tag/commit)
- Domain configuration with validation
- System requirement checks (Docker, memory, disk space, network)
- Step-by-step installation progress with spinners
- Health check waiting
- Success/failure screens with troubleshooting tips

## Building

### Prerequisites

- Go 1.24+

### Build Commands

```bash
cd bin/hobby-installer

# Build for Linux (production - hobby deployments are on Ubuntu)
make

# Or explicitly:
make build-linux
```

This outputs the binary to `bin/posthog-hobby`.

### Testing Locally on macOS

```bash
cd bin/hobby-installer

# Build for macOS
make build-darwin

# Run
../posthog-hobby-darwin
```

Note: The macOS binary (`posthog-hobby-darwin`) is gitignored and only for local testing.

You can also test the `checks` part of the UI in specific with

```bash
cd bin/hobby-installer

# Build and run checks demo
make demo
```

### Other Make Targets

```bash
make deps         # Download dependencies
make clean        # Remove build artifacts
make test         # Run tests
make fmt          # Format code
make help         # Show all available targets
```

## Project Structure

```ls
bin/hobby-installer/
├── main.go           # Entry point, state machine
├── go.mod / go.sum   # Dependencies
├── Makefile          # Build targets
├── ui/
│   ├── styles.go     # Lip Gloss styles (PostHog colors)
│   ├── ascii.go      # ASCII art banner
│   └── components.go # Reusable UI components
├── steps/
│   ├── welcome.go    # Welcome + Install/Upgrade selection
│   ├── version.go    # Version picker
│   ├── domain.go     # Domain input
│   ├── checks.go     # System requirement checks
│   ├── install.go    # Installation progress
│   └── complete.go   # Success/failure screen
└── installer/
    ├── system.go     # OS commands, secret generation
    ├── git.go        # Clone/pull/checkout operations
    ├── env.go        # .env file generation
    ├── geoip.go      # GeoIP database download
    ├── docker.go     # Docker Compose operations
    └── upgrade.go    # Upgrade-specific logic
```

## Usage (Production)

On an Ubuntu server:

```bash
# Download the binary
curl -fsSL https://raw.githubusercontent.com/posthog/posthog/HEAD/bin/posthog-hobby -o posthog-hobby
chmod +x posthog-hobby

# Run the installer
./posthog-hobby
```

## Flow

1. **Welcome** - Choose Install or Upgrade
2. **Version** - Select PostHog version (latest recommended)
3. **Domain** - Enter domain for TLS certificate
4. **Checks** - Verify system requirements
5. **Install** - Clone repo, generate config, start Docker stack
6. **Complete** - Success message with URL or troubleshooting tips
