# Pod Rebalancer

A stateless Go service that monitors Kafka partition load distribution across consumer pods and performs intelligent pod deletion to trigger rebalancing when uneven distribution is detected.

## Overview

The pod rebalancer uses a "rotate outliers" strategy - it identifies the most busy and least busy pods based on composite metrics (CPU usage, Kafka lag, memory usage) and deletes both to trigger Kubernetes to rebalance the load distribution.

## Features

- **Stateless Design**: Runs once, analyzes, acts, and exits - perfect for Kubernetes CronJobs
- **Intelligent Analysis**: Uses composite scoring of CPU, memory, and Kafka metrics
- **Safety First**: Respects minimum pod counts and includes dry-run mode
- **Observability**: Structured logging with zap and Prometheus metrics
- **Production Ready**: Comprehensive testing, security scanning, and Go best practices

## Quick Start

### Prerequisites

- Go 1.21+
- [Task](https://taskfile.dev/installation/) task runner
- Access to VictoriaMetrics/Prometheus endpoint
- Kubernetes cluster access

### Installation

```bash
# Clone the repository (if not already in PostHog monorepo)
git clone <repo-url>
cd pod-rebalancer

# Set up development environment
./scripts/install-tools.sh
task dev-setup

# Build the application
task build
```

### Configuration

Configure via environment variables:

```bash
# Required
export PROMETHEUS_ENDPOINT=http://victoriametrics:8428
export KUBE_NAMESPACE=default
export KUBE_LABEL_SELECTOR=app=consumer

# Thresholds
export CPU_VARIANCE_THRESHOLD=0.3
export LAG_VARIANCE_THRESHOLD=0.5  
export MIN_PODS_REQUIRED=3

# Optional
export DRY_RUN=false
export LOG_LEVEL=info
export PROMETHEUS_TIMEOUT=30s
```

### Usage

```bash
# Run locally (dry-run mode recommended for testing)
export DRY_RUN=true
./bin/rebalancer

# Or with Docker
docker build -t pod-rebalancer .
docker run --rm -e DRY_RUN=true pod-rebalancer
```

## How It Works

1. **Metrics Collection**: Fetches CPU, memory, and Kafka metrics from VictoriaMetrics
2. **Pod State Analysis**: Aggregates metrics into composite scores for each pod
3. **Statistical Analysis**: Calculates load variance and identifies outliers
4. **Decision Making**: Determines if rebalancing is needed based on thresholds
5. **Safe Execution**: Deletes most busy + least busy pods if criteria are met
6. **Observability**: Logs results and exports metrics

## Development

See [docs/development.md](docs/development.md) for detailed development setup and workflow.

### Quick Development Commands

```bash
task dev-setup              # Setup development environment
task check                  # Run all quality checks
task test-coverage          # Run tests with coverage report
task build                  # Build optimized binary
```

## Architecture

The application follows a clean, layered architecture:

- **Layer 1**: Prometheus client (official Go client)
- **Layer 2**: Metrics fetchers (CPU, Kafka, Memory)
- **Layer 3**: Pod state aggregation
- **Layer 4**: Decision engine with outlier strategy
- **Layer 5**: Kubernetes pod operations
- **Layer 6**: Observability (zap logging + Prometheus metrics)

See [specs/architecture.md](specs/architecture.md) for detailed technical architecture.

## Deployment

### Kubernetes CronJob

The service is designed to run as a Kubernetes CronJob:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: pod-rebalancer
spec:
  schedule: "*/5 * * * *"  # Every 5 minutes
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: pod-rebalancer
          containers:
          - name: rebalancer
            image: pod-rebalancer:latest
            env:
            - name: PROMETHEUS_ENDPOINT
              value: "http://victoriametrics:8428"
            - name: KUBE_NAMESPACE
              value: "default"
            - name: KUBE_LABEL_SELECTOR
              value: "app=consumer"
```

### Docker

```bash
# Build optimized image
task docker

# Run with environment variables
docker run --rm \
  -e PROMETHEUS_ENDPOINT=http://victoriametrics:8428 \
  -e DRY_RUN=true \
  pod-rebalancer
```

## Monitoring

### Metrics

The service exports Prometheus metrics:

- `rebalancer_executions_total{status="success|error"}`
- `rebalancer_pods_analyzed_total`
- `rebalancer_pods_deleted_total{type="most_busy|least_busy"}`
- `rebalancer_execution_duration_seconds`
- `rebalancer_load_variance_current`

### Logging

Structured JSON logs with fields:
- `level`: Log level (debug, info, warn, error)
- `msg`: Human-readable message
- `timestamp`: ISO8601 timestamp
- `context`: Additional structured data

## Safety Features

- **Minimum Pod Count**: Prevents deleting pods below configured minimum
- **Dry Run Mode**: Test safely without actual deletions
- **Threshold-Based**: Only acts when variance exceeds configured thresholds
- **Structured Logging**: Complete audit trail of all decisions and actions

## Contributing

1. Follow the development guide in [docs/development.md](docs/development.md)
2. Ensure `task check` passes (formatting, linting, testing, security)
3. Write tests for new functionality
4. Use conventional commit messages

## License

See the main PostHog repository license.