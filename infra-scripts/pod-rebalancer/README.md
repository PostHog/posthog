# PostHog Pod Rebalancer

A stateless Go service that monitors CPU load distribution across Kafka consumer pods and performs intelligent pod deletion to trigger rebalancing when uneven CPU usage distribution is detected.

## Overview

The Pod Rebalancer is designed to run as a Kubernetes CronJob that continuously monitors CPU usage patterns across consumer pods and takes action when load becomes unevenly distributed. It uses a "rotate outliers" strategy - identifying the highest and lowest CPU usage pods and deleting them to trigger Kubernetes to rebalance the workload.

### Key Features

- **🎯 CPU-Focused**: Analyzes CPU usage patterns using VictoriaMetrics/Prometheus queries
- **⚡ Stateless Design**: Runs once, analyzes, acts, and exits - perfect for CronJobs
- **🛡️ Safety First**: Respects minimum pod counts, includes dry-run mode, and HPA-aware thresholds
- **📊 HPA Integration**: Uses HPA target metrics and tolerance multipliers for intelligent decisions
- **🔍 Comprehensive Testing**: 67+ unit and integration tests with mock servers
- **🏗️ Production Ready**: Multi-stage Docker builds, structured logging, and observability

## How It Works

1. **Metrics Collection**: Queries VictoriaMetrics for real-time CPU usage across pods
2. **HPA Analysis**: Fetches HPA targets and calculates tolerance thresholds  
3. **Outlier Detection**: Identifies pods with highest/lowest CPU usage using PromQL topk/bottomk
4. **Smart Decision Making**: Only acts when CPU variance exceeds HPA-based thresholds
5. **Safe Execution**: Deletes selected pods while respecting minimum pod requirements
6. **Observability**: Structured logging and metrics for monitoring and debugging

## Quick Start

### Prerequisites

- Go 1.25+ 
- Kubernetes cluster access
- VictoriaMetrics/Prometheus endpoint
- HPA configured for target deployment

### Installation & Usage

```bash
# 1. Clone and build
git clone <posthog-repo>
cd infra-scripts/pod-rebalancer
go build -o bin/rebalancer ./cmd/rebalancer

# 2. Configure environment variables
export PROMETHEUS_ENDPOINT="http://victoriametrics:8428"
export KUBE_NAMESPACE="posthog"
export DEPLOYMENT_NAME="ingestion-consumer"
export DRY_RUN="true"  # Safe testing mode

# 3. Run locally (dry-run recommended for testing)
./bin/rebalancer

# 4. Or with Docker
docker build -f deploy/docker/Dockerfile -t pod-rebalancer .
docker run --rm -e DRY_RUN=true pod-rebalancer
```

### Command Line Options

```bash
./bin/rebalancer --help     # Show usage and configuration options
./bin/rebalancer --version  # Show version information
```

## Configuration

The service is configured via environment variables:

### Required Configuration

```bash
# Prometheus/VictoriaMetrics endpoint
PROMETHEUS_ENDPOINT=http://victoriametrics:8428

# Kubernetes targeting
KUBE_NAMESPACE=posthog                    # Namespace containing pods
DEPLOYMENT_NAME=ingestion-consumer        # Container name for metrics queries
```

### Optional Configuration

```bash
# Connection settings
PROMETHEUS_TIMEOUT=30s                    # Query timeout (default: 30s)
KUBE_LABEL_SELECTOR=app=consumer         # Pod label selector (default: app=consumer)

# Decision parameters
METRICS_TIME_WINDOW=5m                    # CPU rate calculation window (default: 5m)
REBALANCE_TOP_K_PODS=2                   # Number of high/low pods to consider (default: 2)
TOLERANCE_MULTIPLIER=1.5                 # HPA threshold multiplier (default: 1.5)
MINIMUM_IMPROVEMENT_PERCENT=10.0         # Required improvement % (default: 10.0)
HPA_PREFIX=keda-hpa-                     # HPA name prefix (default: empty)

# Safety settings
MINIMUM_PODS_REQUIRED=3                  # Minimum pods to maintain (default: 3)
DRY_RUN=false                           # Enable dry-run mode (default: false)
LOG_LEVEL=info                          # Logging level (default: info)
```

## Deployment

### Kubernetes CronJob (Recommended)

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: pod-rebalancer
  namespace: posthog
spec:
  schedule: "*/10 * * * *"  # Every 10 minutes
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: pod-rebalancer
          restartPolicy: Never
          containers:
          - name: rebalancer
            image: posthog/pod-rebalancer:latest
            resources:
              requests:
                cpu: 100m
                memory: 128Mi
              limits:
                cpu: 500m
                memory: 256Mi
            env:
            - name: PROMETHEUS_ENDPOINT
              value: "http://victoriametrics:8428"
            - name: KUBE_NAMESPACE
              value: "posthog"
            - name: DEPLOYMENT_NAME
              value: "ingestion-consumer"
            - name: LOG_LEVEL
              value: "info"
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: pod-rebalancer
  namespace: posthog
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: pod-rebalancer
  namespace: posthog
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list", "delete"]
- apiGroups: ["autoscaling"]
  resources: ["horizontalpodautoscalers"]
  verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: pod-rebalancer
  namespace: posthog
subjects:
- kind: ServiceAccount
  name: pod-rebalancer
  namespace: posthog
roleRef:
  kind: Role
  name: pod-rebalancer
  apiGroup: rbac.authorization.k8s.io
```

### Docker Deployment

```bash
# Build optimized production image (68.5MB)
docker build -f deploy/docker/Dockerfile -t pod-rebalancer .

# Run with full configuration
docker run --rm \
  -e PROMETHEUS_ENDPOINT="http://victoriametrics:8428" \
  -e KUBE_NAMESPACE="posthog" \
  -e DEPLOYMENT_NAME="ingestion-consumer" \
  -e DRY_RUN="false" \
  pod-rebalancer
```

## Architecture

The application follows clean architecture principles:

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   main.go       │    │  Configuration   │    │    Logging      │
│   CLI & Setup   │───▶│  (Viper + Env)   │───▶│  (Zap Logger)   │
└─────────────────┘    └──────────────────┘    └─────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Core Application Loop                      │
├─────────────────┬─────────────────┬─────────────────────────────┤
│ Prometheus      │ CPU Metrics     │ Decision Engine             │
│ Client          │ Fetcher         │ (HPA-aware analysis)        │
│ (HTTP + PromQL) │ (topk/bottomk)  │ (variance + thresholds)     │
└─────────────────┴─────────────────┴─────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Kubernetes Manager                           │
│          (Pod validation + deletion + safety checks)           │
└─────────────────────────────────────────────────────────────────┘
```

### Core Components

- **Prometheus Client** (`pkg/prometheus`): HTTP client with PromQL query execution
- **CPU Metrics** (`pkg/metrics`): Specialized CPU usage fetching with HPA integration  
- **Decision Engine** (`pkg/decision`): Statistical analysis and rebalancing logic
- **Kubernetes Manager** (`pkg/kubernetes`): Safe pod operations with validation
- **Configuration** (`pkg/config`): Environment-based config with Viper
- **Logging** (`pkg/logging`): Structured logging with zap and metrics

## Development

### Development Setup

```bash
# Install Go 1.25+ and development tools
go version  # Should be 1.25+

# Clone and setup
cd infra-scripts/pod-rebalancer
go mod download

# Run tests
go test ./...                    # All tests
go test -v ./pkg/metrics/...     # Specific package
go test -run TestCPUMetrics      # Specific test

# Run integration tests  
go test -v ./test/...            # Full integration test suite

# Build and test locally
go build -o bin/rebalancer ./cmd/rebalancer
export DRY_RUN=true
./bin/rebalancer
```

### Project Structure

```
├── cmd/rebalancer/           # Main application entry point
├── pkg/                      # Core packages
│   ├── config/              # Configuration management (Viper)
│   ├── prometheus/          # Prometheus/VictoriaMetrics client
│   ├── metrics/             # CPU metrics fetching and analysis
│   ├── decision/            # Rebalancing decision engine
│   ├── kubernetes/          # K8s pod management and safety
│   └── logging/             # Structured logging and metrics
├── test/                    # Integration tests (Ginkgo + Gomega)
├── examples/                # Usage examples and sample configs  
├── deploy/docker/           # Multi-stage Dockerfile
├── docs/                    # Additional documentation
└── specs/                   # Technical specifications and plans
```

### Testing Strategy

The project includes comprehensive testing:

- **Unit Tests**: 57+ tests across all packages using Go's testing framework and Ginkgo/Gomega
- **Integration Tests**: 10 test scenarios with mock Prometheus server and fake Kubernetes client
- **Example Tests**: Validation that examples work correctly
- **Performance Tests**: Ensuring operations complete within reasonable timeframes

```bash
# Run all tests
go test ./...

# Run with coverage
go test -coverprofile=coverage.out ./...
go tool cover -html=coverage.out

# Run integration tests specifically
go test -v ./test/
```

## Monitoring & Observability

### Structured Logging

All operations are logged with structured JSON using zap:

```json
{
  "level": "info",
  "ts": 1640995200.123,
  "caller": "decision/engine.go:45",
  "msg": "CPU analysis completed",
  "namespace": "posthog",
  "deployment": "ingestion-consumer",
  "pod_count": 5,
  "avg_cpu": 0.45,
  "cpu_variance": 0.12,
  "rebalance_needed": true
}
```

### Key Log Events

- **Configuration loading**: Environment variable validation and defaults
- **Prometheus connectivity**: Connection health and query execution
- **CPU analysis**: Detailed metrics collection and statistical analysis
- **Decision making**: Threshold comparisons and rebalancing decisions
- **Pod operations**: Validation, deletion attempts, and safety checks
- **Error handling**: Network failures, invalid configurations, and API errors

### Production Monitoring

Monitor these key indicators:

- **Successful executions**: Regular CronJob completion without errors
- **CPU variance trends**: Whether rebalancing is reducing CPU distribution variance
- **Pod deletion frequency**: How often pods are being rebalanced
- **Error rates**: Failed Prometheus queries or Kubernetes operations
- **Execution duration**: Time taken for full analysis cycle

## Safety Features

- **Minimum Pod Count**: Never delete pods below configured minimum threshold
- **Dry Run Mode**: Test all logic without actual pod deletions (`DRY_RUN=true`)
- **HPA Integration**: Only acts when CPU usage significantly exceeds HPA targets
- **Threshold-Based Decisions**: Multiple safeguards before any pod deletion
- **Graceful Error Handling**: Fails fast with clear error messages for debugging
- **Audit Trail**: Complete structured logging of all decisions and actions

## Troubleshooting

### Common Issues

**Connection Errors**
```bash
# Test Prometheus connectivity
curl -X POST http://victoriametrics:8428/api/v1/query \
  -d 'query=up' \
  -d 'time=now'

# Check Kubernetes access
kubectl get pods -n posthog -l app=consumer
```

**No Pods Found**
- Verify `KUBE_NAMESPACE` and `KUBE_LABEL_SELECTOR` match your pods
- Ensure `DEPLOYMENT_NAME` matches your container name exactly
- Check that pods have CPU metrics available in VictoriaMetrics

**No Rebalancing Actions**
- Enable debug logging: `LOG_LEVEL=debug`
- Verify HPA configuration and targets
- Check if CPU variance exceeds thresholds
- Confirm minimum pod count requirements

**Permission Errors**
- Verify ServiceAccount has proper RBAC permissions for pods and HPA
- Check namespace isolation and cross-namespace access

### Debug Mode

```bash
# Enable detailed debugging
export LOG_LEVEL=debug
export DRY_RUN=true
./bin/rebalancer

# This will show:
# - All PromQL queries being executed
# - Raw Prometheus response data  
# - Statistical calculations and thresholds
# - Decision-making logic step-by-step
# - Pod selection reasoning
```

## Contributing

1. **Follow Go best practices**: Use `gofmt`, `golint`, and `go vet`
2. **Write tests**: Unit tests for new functionality, integration tests for workflows
3. **Update documentation**: Keep README and technical specs current
4. **Use conventional commits**: Clear commit messages describing changes
5. **Test thoroughly**: Run full test suite and manual testing in dry-run mode

## License

This project is part of PostHog and follows the main repository's license terms.