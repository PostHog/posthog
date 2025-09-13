# Pod Rebalancer - Technical Specification

## Overview

A Go-based service that monitors Kafka partition load distribution across pods and performs intelligent pod deletion to trigger rebalancing when uneven distribution is detected.

## Problem Statement

Kafka partitions are sometimes distributed unevenly across consumer pods, leading to:
- Some pods handling significantly more load than others
- Inefficient resource utilization
- Performance bottlenecks on heavily loaded pods

## Solution

A monitoring service that:
1. Queries VictoriaMetrics for pod-level metrics
2. Analyzes load distribution patterns
3. Selectively deletes pods to trigger Kubernetes rebalancing

## Requirements

### Functional Requirements

1. **Metrics Collection**
   - Connect to VictoriaMetrics endpoint via Prometheus client
   - Fetch CPU usage, memory usage per pod
   - Retrieve Kafka-specific metrics (lag, consumption rate, production rate)

2. **Load Analysis**
   - Calculate load distribution statistics
   - Identify pods with highest and lowest load
   - Determine if rebalancing is needed based on configured thresholds
   - Support multiple load indicators (CPU, Kafka lag, message throughput)

3. **Pod Management**
   - Delete pods via Kubernetes API

4. **Configuration Management**
   - Environment variable configuration
   - Runtime configuration validation

5. **Safety & Reliability**
   - Graceful degradation when metrics unavailable
   - Prevent deletion of critical/system pods
   - Support dry-run mode for testing
   - Comprehensive logging and observability

### Non-Functional Requirements

1. **Performance**
   - Execute analysis cycle within 30 seconds
   - Support monitoring 1000+ pods

2. **Reliability**
   - Handle network failures gracefully
   - Retry failed operations with exponential backoff

3. **Observability**
   - Structured logging with configurable levels
   - Prometheus metrics export
   - Operational dashboards support

4. **Security**
   - Use Kubernetes service account tokens
   - Audit trail for all pod deletions

## Configuration

Configuration is managed through environment variables:

```bash
# Prometheus/VictoriaMetrics
PROMETHEUS_ENDPOINT=http://victoriametrics:8428
PROMETHEUS_TIMEOUT=30s

# Kubernetes
KUBE_NAMESPACE=default
KUBE_LABEL_SELECTOR=app=consumer

# Decision making
CPU_VARIANCE_THRESHOLD=0.3
LAG_VARIANCE_THRESHOLD=0.5
MIN_PODS_REQUIRED=3

# Safety
DRY_RUN=false
LOG_LEVEL=info
```

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

## Monitoring & Alerting

### Key Metrics
- `rebalancer_cycles_total{status}`
- `rebalancer_pods_deleted_total`
- `rebalancer_analysis_duration_seconds`
- `rebalancer_api_errors_total`

### Critical Alerts
- Persistent API failures
- Configuration validation errors
- Excessive pod deletion rates
- Circuit breaker activation

## Security Considerations

1. **Least Privilege**: Minimal RBAC permissions
2. **Audit Trail**: Comprehensive logging of all actions
3. **Input Validation**: Strict configuration validation
4. **Secrets Management**: Kubernetes secrets for sensitive data

## Future Enhancements

1. Machine learning-based load prediction
2. Multi-cluster support
3. Integration with other rebalancing systems
4. Advanced scheduling algorithms
5. Real-time decision making capabilities
