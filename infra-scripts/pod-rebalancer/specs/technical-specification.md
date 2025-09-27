# Pod Rebalancer - Technical Specification (CPU-Only Focus)

## Overview

A Go-based service that monitors CPU load distribution across consumer pods and performs intelligent pod deletion to trigger rebalancing when CPU usage variance exceeds thresholds.

**Architecture Decision**: This initial implementation focuses exclusively on CPU metrics to reduce complexity and deliver faster. Future iterations can add Kafka lag and memory metrics if needed.

## Problem Statement

Consumer pods sometimes experience uneven CPU load distribution, leading to:
- Some pods consuming significantly more CPU than others
- Inefficient resource utilization across the pod fleet
- Performance bottlenecks on heavily loaded pods
- Suboptimal processing throughput

## Solution

A CPU-focused monitoring service that:
1. Queries VictoriaMetrics for pod-level CPU usage metrics using PostHog-specific queries
2. Analyzes CPU load variance across pods using statistical methods
3. Selectively deletes highest and lowest CPU usage pods to trigger Kubernetes rebalancing

## Requirements

### Functional Requirements

1. **CPU Metrics Collection**
   - Connect to VictoriaMetrics endpoint via custom HTTP client
   - Fetch per-pod CPU usage using PostHog-specific container queries
   - Retrieve CPU limits and requests for resource planning
   - Use literal container name matching instead of regex patterns

2. **CPU Load Analysis**
   - Calculate CPU usage distribution statistics (mean, variance, std dev)
   - Identify pods with highest and lowest CPU usage
   - Determine if rebalancing is needed based on CPU variance threshold
   - Focus exclusively on CPU metrics for decision making

3. **Pod Management**
   - Delete selected pods via Kubernetes API
   - Always select highest CPU and lowest CPU pods for deletion
   - Respect minimum pod count safety constraints

4. **Configuration Management**
   - Environment variable configuration using Viper library
   - Runtime configuration validation with comprehensive error handling
   - Required deployment name configuration (no defaults)

5. **Safety & Reliability**
   - Graceful degradation when CPU metrics unavailable
   - Prevent deletion below minimum pod threshold
   - Support dry-run mode for testing
   - Comprehensive structured logging with zap

### Non-Functional Requirements

1. **Performance**
   - Execute CPU analysis cycle within 30 seconds
   - Support monitoring 1000+ pods with CPU metrics only

2. **Reliability**
   - Handle network failures gracefully
   - Fail fast with clear error messages (no retries - let CronJob handle)

3. **Observability**
   - Structured logging with configurable levels using zap
   - Prometheus metrics export for CPU variance tracking
   - Clear logs for all CPU-based decisions

4. **Security**
   - Use Kubernetes service account tokens
   - Audit trail for all CPU-based pod deletions

## Configuration

Configuration is managed through environment variables using Viper:

```bash
# Prometheus/VictoriaMetrics
PROMETHEUS_ENDPOINT=http://victoriametrics:8428       # Default: http://localhost:9090
PROMETHEUS_TIMEOUT=30s                                # Default: 30s

# Kubernetes & Container Targeting
KUBE_NAMESPACE=posthog                                # Default: posthog
KUBE_LABEL_SELECTOR=app=consumer                      # Default: app=consumer
DEPLOYMENT_NAME=ingestion-consumer                    # Required - no default
METRICS_TIME_WINDOW=5m                                # Default: 5m

# CPU-Only Decision Making
CPU_VARIANCE_THRESHOLD=0.3                            # Default: 0.3
MIN_PODS_REQUIRED=3                                   # Default: 3

# Safety & Logging
DRY_RUN=false                                        # Default: false
LOG_LEVEL=info                                       # Default: info
```

**Key Changes**:
- `DEPLOYMENT_NAME` is required with no default (literal container matching)
- `METRICS_TIME_WINDOW` controls PromQL rate calculation window
- Removed `LAG_VARIANCE_THRESHOLD` (CPU-only approach)
- All config managed by Viper with proper validation

## Deployment

### Docker Image
```dockerfile
FROM golang:1.21-alpine AS builder
# Build optimized binary

FROM alpine:latest
RUN apk --no-cache add ca-certificates
# Minimal runtime environment
```

### Kubernetes Deployment
- CronJob resource for scheduled execution (every 5 minutes)
- ServiceAccount with minimal required permissions

## Monitoring & Alerting (CPU-Focused)

### Key Metrics
- `rebalancer_executions_total{status="success|error"}`
- `rebalancer_pods_analyzed_total`
- `rebalancer_pods_deleted_total{type="highest_cpu|lowest_cpu"}`
- `rebalancer_execution_duration_seconds`
- `rebalancer_cpu_variance_current`
- `rebalancer_cpu_usage_mean`
- `rebalancer_cpu_usage_stddev`

### Critical Alerts
- Consecutive execution failures (3+)
- No pods found matching selector
- Excessive pod deletions (>50% of pods)
- High CPU variance persisting (>threshold for 30+ minutes)
- CPU metrics collection failures

## Security Considerations

1. **Least Privilege**: Minimal RBAC permissions
2. **Audit Trail**: Comprehensive logging of all actions
3. **Input Validation**: Strict configuration validation
4. **Secrets Management**: Kubernetes secrets for sensitive data

## Future Enhancements

**Phase 2 - Additional Metrics**:
1. Add Kafka lag metrics support
2. Add memory usage metrics support
3. Implement composite scoring algorithm combining CPU, Kafka, and memory

**Current Focus**: Deliver robust CPU-only implementation first, then iterate based on operational experience.
