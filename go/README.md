# PostHog Go Services

This directory contains Go services and shared libraries for PostHog.

## Structure

```
.
├── pkg/           # Shared packages
│   └── common/    # Common utilities and types
└── services/      # Individual services
    └── livestream/
    └── capture/
    └── ...
```

## Development

### Prerequisites

-   Go 1.21 or later
-   golangci-lint (for linting)
-   Docker (for containerized builds)

### Workspace Setup

This repository uses Go workspaces (go.work) to manage multiple modules. The workspace includes:

-   Root module (`.`)
-   Common package (`pkg/common`)
-   Individual services (e.g., `services/livestream`)

When developing locally, the workspace automatically handles dependencies between modules. You can run commands from the root `go` directory and they will work across all modules.

### Commands

```bash
# Build all services
make build

# Run tests
make test

# Run linter
make lint

# Clean build artifacts
make clean

# Sync workspace dependencies
go work sync
```

### Running Individual Services

```bash
# Run a service directly
make run-<service>

# Example for livestream
make run-livestream

# Build a single service (output in bin/)
make build-<service>

# Example for livestream
make build-livestream
./bin/livestream

# Run tests for a single service
make test-<service>

# Example for livestream
make test-livestream
```

### Docker Builds

Each service has its own Dockerfile. To build a service:

```bash
# From the root directory
docker build -t posthog/<service> -f Dockerfile.<service> .

# Example for livestream service
docker build -t posthog/livestream -f Dockerfile.livestream .
```

To run a built container:

```bash
docker run -p 8000:8000 posthog/<service>

# Example for livestream service
docker run -p 8000:8000 posthog/livestream
```

### Adding a New Service

1. Create a new directory under `services/`
2. Initialize a new module:
    ```bash
    cd services/myservice
    go mod init github.com/PostHog/posthog/go/services/myservice
    ```
3. Add the new module to `go.work`:
    ```bash
    go work use ./services/myservice
    ```
4. Import common packages as needed:
    ```go
    import "github.com/PostHog/posthog/go/pkg/common"
    ```

### Common Package

The `pkg/common` directory contains shared code used across services. Add reusable components here that may be needed by multiple services.
