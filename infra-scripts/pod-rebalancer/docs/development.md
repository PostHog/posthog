# Pod Rebalancer - Development Guide

This guide helps you set up a development environment for the pod rebalancer.

## Prerequisites

- Go 1.25 or later
- [Task](https://taskfile.dev/installation/) - Task runner
- [direnv](https://direnv.net/docs/installation.html) - Environment variable management (optional but recommended)

## Quick Start

1. **Clone and setup the project:**
   ```bash
   cd pod-rebalancer
   ./scripts/install-tools.sh  # Install development tools
   task dev-setup              # Initialize project dependencies
   ```

2. **Configure environment (if using direnv):**
   ```bash
   direnv allow                # Load .envrc environment variables
   ```

3. **Verify setup:**
   ```bash
   task check                  # Run all quality checks
   task build                  # Build the binary
   ```

## Development Workflow

### Essential Commands

```bash
# Setup
task dev-setup              # Install tools and dependencies

# Code quality
task fmt                    # Format code and organize imports
task lint                   # Run golangci-lint
task vet                    # Run go vet
task check                  # Run all quality checks (fmt, vet, lint, test, security)

# Testing
task test                   # Run tests with race detection
task test-coverage          # Generate coverage report (HTML)

# Security
task security               # Run govulncheck for vulnerabilities

# Build
task build                  # Build optimized binary
task clean                  # Clean build artifacts

# Docker
task docker                 # Build Docker image
```

### Code Quality Standards

All code must pass these checks before committing:

- **Formatting**: `gofmt` and `goimports` for consistent formatting
- **Linting**: `golangci-lint` with strict rules (see `.golangci.yml`)
- **Vetting**: `go vet` for potential issues
- **Testing**: Unit tests with race detection
- **Security**: `govulncheck` for known vulnerabilities

### Project Structure

```
pod-rebalancer/
├── cmd/rebalancer/          # Application entrypoint
├── pkg/                     # Public packages
│   ├── prometheus/          # Prometheus client
│   ├── metrics/             # Metrics fetchers
│   ├── podstate/            # Pod state aggregation
│   ├── decision/            # Rebalancing decisions
│   ├── kubernetes/          # Kubernetes operations
│   ├── config/              # Configuration management
│   └── logging/             # Structured logging
├── internal/                # Private packages
├── specs/                   # Project specifications
├── docs/                    # Documentation
└── scripts/                 # Development scripts
```

## Environment Variables

Development environment variables are managed in `.envrc`:

```bash
# Prometheus/VictoriaMetrics
PROMETHEUS_ENDPOINT=http://localhost:9090
PROMETHEUS_TIMEOUT=30s

# Kubernetes
KUBE_NAMESPACE=default
KUBE_LABEL_SELECTOR=app=consumer

# Thresholds
CPU_VARIANCE_THRESHOLD=0.3
LAG_VARIANCE_THRESHOLD=0.5
MIN_PODS_REQUIRED=3

# Development
DRY_RUN=true
LOG_LEVEL=debug
```

## Testing

### Running Tests

```bash
task test                   # Run all tests
task test-coverage          # Generate coverage report
go test ./pkg/config/       # Run specific package tests
go test -run TestFuncName   # Run specific test
```

### Writing Tests

- Use `github.com/stretchr/testify` for assertions
- Follow table-driven test patterns for multiple test cases
- Mock external dependencies (Kubernetes, Prometheus)
- Aim for >90% coverage

Example:
```go
func TestConfigLoad(t *testing.T) {
    tests := []struct {
        name string
        env  map[string]string
        want *Config
        err  bool
    }{
        // test cases
    }

    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            // test implementation
        })
    }
}
```

## Debugging

### Local Development

1. Set `DRY_RUN=true` in `.envrc` for safe testing
2. Use `LOG_LEVEL=debug` for detailed logging
3. Point `PROMETHEUS_ENDPOINT` to a local Prometheus instance

### Common Issues

- **Import organization**: Run `task fmt` to fix import order
- **Linting failures**: Check `.golangci.yml` for enabled rules
- **Test failures**: Use `go test -v` for verbose output
- **Build failures**: Ensure all dependencies are in `go.mod`

## Contributing

1. Make changes in a feature branch
2. Run `task check` to ensure quality standards
3. Add tests for new functionality
4. Update documentation if needed
5. Commit using conventional commit format

## Tools Configuration

- **golangci-lint**: `.golangci.yml`
- **Task runner**: `Taskfile.yml`
- **Go modules**: `go.mod`, `go.sum`
- **Environment**: `.envrc`
- **Git ignore**: `.gitignore`
