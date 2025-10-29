# PostHog/charts: LLM Analytics Temporal Worker Setup

This document provides instructions for setting up the LLM Analytics Temporal Worker in the PostHog/charts repository.

## Background

We're migrating LLM evaluation workflows from `general-purpose-task-queue` to a dedicated `llm-analytics-task-queue` to provide:

- Better resource isolation
- Independent scaling
- Dedicated monitoring
- Clearer ownership

## Required Changes in PostHog/charts

### 1. Create Kubernetes Deployment

Create a new temporal worker deployment based on an existing worker template (e.g., `temporal-worker-weekly-digest` or `temporal-worker-messaging`).

**Key Configuration:**

- **Release Name:** `temporal-worker-llm-analytics`
- **Task Queue:** `llm-analytics-task-queue`
- **Metrics Port:** `8013`

**Command Arguments:**

```yaml
args:
    - start_temporal_worker
    - --task-queue
    - llm-analytics-task-queue
    - --metrics-port
    - '8013'
```

### 2. Resource Configuration

**Suggested Starting Resources:**

```yaml
resources:
    requests:
        cpu: 500m
        memory: 1Gi
    limits:
        cpu: 2000m
        memory: 4Gi
```

**Autoscaling:**

```yaml
autoscaling:
    enabled: true
    minReplicas: 1
    maxReplicas: 10
    targetCPUUtilizationPercentage: 70
    targetMemoryUtilizationPercentage: 80
```

Adjust these values based on expected evaluation workload.

### 3. Environment Variables

Ensure the worker has access to:

- `TEMPORAL_HOST` - Temporal server address
- `TEMPORAL_NAMESPACE` - Temporal namespace (usually "default")
- `TEMPORAL_CLIENT_ROOT_CA` - TLS root CA certificate (for Temporal Cloud)
- `TEMPORAL_CLIENT_CERT` - TLS client certificate (for Temporal Cloud)
- `TEMPORAL_CLIENT_KEY` - TLS client key (for Temporal Cloud)
- All standard Django/PostHog environment variables
- Database connection strings (Postgres, ClickHouse)
- OpenAI API key (for LLM judge execution)

### 4. Service Configuration

**Prometheus Metrics Service:**

```yaml
service:
    type: ClusterIP
    ports:
        - name: metrics
          port: 8013
          targetPort: 8013
          protocol: TCP
```

### 5. ServiceMonitor (if using Prometheus Operator)

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
    name: temporal-worker-llm-analytics
spec:
    selector:
        matchLabels:
            app: temporal-worker-llm-analytics
    endpoints:
        - port: metrics
          interval: 30s
          path: /metrics
```

### 6. Labels and Annotations

**Standard Labels:**

```yaml
labels:
    app: temporal-worker-llm-analytics
    component: temporal-worker
    team: llm-analytics
```

**Annotations:**

```yaml
annotations:
    prometheus.io/scrape: 'true'
    prometheus.io/port: '8013'
    prometheus.io/path: '/metrics'
```

### 7. Example Structure

You can base the new worker on the Weekly Digest worker or Messaging worker, which have similar characteristics:

```
charts/
├── temporal-worker-llm-analytics/
│   ├── Chart.yaml
│   ├── values.yaml
│   ├── templates/
│   │   ├── deployment.yaml
│   │   ├── service.yaml
│   │   ├── servicemonitor.yaml
│   │   ├── configmap.yaml (if needed)
│   │   └── _helpers.tpl
```

### 8. Deployment Configuration

**Image Configuration:**

```yaml
image:
    repository: posthog/posthog
    pullPolicy: IfNotPresent
    tag: '' # Will be set by CD pipeline
```

**Security Context:**

```yaml
securityContext:
    runAsNonRoot: true
    runAsUser: 1000
    fsGroup: 1000
    capabilities:
        drop:
            - ALL
```

**Health Checks:**
The worker doesn't typically expose HTTP health endpoints, but you can configure:

```yaml
livenessProbe:
    exec:
        command:
            - python
            - -c
            - 'import sys; sys.exit(0)'
    initialDelaySeconds: 30
    periodSeconds: 30
    timeoutSeconds: 5
```

### 9. Namespace

Deploy to the same namespace as other temporal workers (typically the main PostHog namespace).

### 10. Secrets

The worker needs access to:

- `posthog-secrets` - Main PostHog secrets (database, credentials)
- `temporal-tls-certs` - Temporal Cloud TLS certificates
- Any LLM-specific secrets (OpenAI API keys, etc.)

## Testing the Deployment

After deploying:

1. **Check pod status:**

    ```bash
    kubectl get pods -l app=temporal-worker-llm-analytics
    ```

2. **Check logs:**

    ```bash
    kubectl logs -l app=temporal-worker-llm-analytics --tail=100
    ```

    Look for: `"🤖 Starting Temporal worker"` and worker registration messages

3. **Verify in Temporal Cloud UI:**
    - Navigate to Temporal Cloud UI
    - Check that `llm-analytics-task-queue` appears in the task queues list
    - Verify the worker is polling the queue

4. **Check metrics:**

    ```bash
    kubectl port-forward service/temporal-worker-llm-analytics 8013:8013
    curl http://localhost:8013/metrics
    ```

    Look for `temporal_*` and `evaluation_*` metrics

5. **Test with a workflow:**
    - Trigger a manual evaluation via the PostHog API
    - Verify the workflow runs successfully on the new queue
    - Check workflow history in Temporal UI

## Monitoring

Key metrics to monitor:

- `temporal_worker_task_queue_poll_total` - Worker polling activity
- `temporal_activity_execution_total` - Activity execution count
- `temporal_activity_execution_failed_total` - Failed activities
- `temporal_workflow_completed_total` - Completed workflows
- `evaluation_run_workflows_started` - LLM Analytics specific metric
- `evaluation_scheduler_events_processed` - Scheduler activity

Set up alerts for:

- Worker pod crashes/restarts
- High activity failure rate
- Queue backlog growth
- Workflow timeouts

## Rollback Plan

If issues arise:

1. Keep the worker deployment running
2. Revert the posthog repo changes that switched clients to the new queue
3. Workflows will go back to `general-purpose-task-queue`
4. The dedicated worker will sit idle but harmless

## References

- Similar workers to reference: `temporal-worker-weekly-digest`, `temporal-worker-messaging`
- Temporal documentation: https://docs.temporal.io/
- PostHog worker base image: `posthog/posthog`

## Questions?

Contact the LLM Analytics team if you have questions about:

- Expected workload/scaling requirements
- Environment-specific configurations
- Testing and validation
