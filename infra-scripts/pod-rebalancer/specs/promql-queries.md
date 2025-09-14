# PromQL Queries for CPU Rebalancing Algorithm

## Base Metrics Collection

### 1. **HPA Target Utilization**
```promql
# Get HPA target utilization percentage (0-100)
kube_horizontalpodautoscaler_spec_target_metric{
  horizontalpodautoscaler=~"(keda-hpa-)?ingestion-events", 
  namespace="posthog",
  metric_name="cpu"
}
```

### 2. **Per-Pod CPU Usage**
```promql
# CPU usage per pod in cores per second
sum by(pod) (rate(container_cpu_usage_seconds_total{
  namespace="posthog", 
  container="ingestion-events"
}[5m]))
```

### 3. **Per-Pod CPU Requests**
```promql
# CPU requests per pod in cores
sum by(pod) (kube_pod_container_resource_requests{
  resource="cpu", 
  namespace="posthog", 
  container="ingestion-events"
})
```

### 4. **Per-Pod CPU Utilization Percentage**
```promql
# CPU utilization as percentage of requests
(
  sum by(pod) (rate(container_cpu_usage_seconds_total{
    namespace="posthog", 
    container="ingestion-events"
  }[5m])) /
  sum by(pod) (kube_pod_container_resource_requests{
    resource="cpu", 
    namespace="posthog", 
    container="ingestion-events"
  })
) * 100
```

## Algorithm Implementation Queries

### 5. **Target CPU Usage (Absolute)**
```promql
# Target CPU usage in cores = HPA target % * CPU request
scalar(kube_horizontalpodautoscaler_spec_target_metric{
  horizontalpodautoscaler=~"(keda-hpa-)?ingestion-events", 
  namespace="posthog",
  metric_name="cpu"
}) / 100 *
avg(kube_pod_container_resource_requests{
  resource="cpu", 
  namespace="posthog", 
  container="ingestion-events"
})
```

### 6. **Top K Pods (Highest CPU Usage)**
```promql
# Top 2 CPU consuming pods
topk(2, sum by(pod) (rate(container_cpu_usage_seconds_total{
  namespace="posthog", 
  container="ingestion-events"
}[5m])))
```

### 7. **Bottom K Pods (Lowest CPU Usage)**
```promql  
# Bottom 2 CPU consuming pods
bottomk(2, sum by(pod) (rate(container_cpu_usage_seconds_total{
  namespace="posthog", 
  container="ingestion-events"
}[5m])))
```

### 8. **Current Average CPU Usage (All Pods)**
```promql
# Average CPU usage across all pods
avg(sum by(pod) (rate(container_cpu_usage_seconds_total{
  namespace="posthog", 
  container="ingestion-events"
}[5m])))
```

### 9. **Top K Pods Average CPU Usage**
```promql
# Average CPU of top 2 pods - this is approximated since we can't directly avg topk results
# In implementation, we'll fetch the actual values and compute in Go code
quantile(0.75, sum by(pod) (rate(container_cpu_usage_seconds_total{
  namespace="posthog", 
  container="ingestion-events"
}[5m])))
```

### 10. **Bottom K Pods Average CPU Usage**
```promql
# Average CPU of bottom 2 pods - approximated with quantile
quantile(0.25, sum by(pod) (rate(container_cpu_usage_seconds_total{
  namespace="posthog", 
  container="ingestion-events"
}[5m])))
```

### 11. **Safety Threshold Check**
```promql
# Check if top pods are above safety threshold (120% of target by default)
topk(2, sum by(pod) (rate(container_cpu_usage_seconds_total{
  namespace="posthog", 
  container="ingestion-events"  
}[5m]))) >
scalar(kube_horizontalpodautoscaler_spec_target_metric{
  horizontalpodautoscaler=~"(keda-hpa-)?ingestion-events", 
  namespace="posthog",
  metric_name="cpu"
}) / 100 * 1.2 *
avg(kube_pod_container_resource_requests{
  resource="cpu", 
  namespace="posthog", 
  container="ingestion-events"
})
```

### 12. **Variance Check**
```promql
# Check if there's sufficient variance between top and bottom pods
max(sum by(pod) (rate(container_cpu_usage_seconds_total{
  namespace="posthog", 
  container="ingestion-events"
}[5m]))) -
min(sum by(pod) (rate(container_cpu_usage_seconds_total{
  namespace="posthog", 
  container="ingestion-events"
}[5m]))) >
scalar(kube_horizontalpodautoscaler_spec_target_metric{
  horizontalpodautoscaler=~"(keda-hpa-)?ingestion-events", 
  namespace="posthog",
  metric_name="cpu"
}) / 100 * 0.1 *
avg(kube_pod_container_resource_requests{
  resource="cpu", 
  namespace="posthog", 
  container="ingestion-events"
})
```

## Implementation Notes

### For Go Implementation:

1. **Fetch Individual Values**: Use queries #1-4 to get base data
2. **Compute in Go**: Calculate averages, improvements, and thresholds in Go code rather than complex PromQL
3. **Simplified PromQL**: Keep Prometheus queries simple and do complex logic in application code

### Example Go Algorithm Flow:
```go
// 1. Fetch base data
hpaTarget := queryHPATarget()
cpuUsagePerPod := queryCPUUsagePerPod()  
cpuRequestPerPod := queryCPURequestPerPod()

// 2. Calculate derived values
targetCPUUsage := hpaTarget / 100 * avgCPURequest
topKPods := selectTopK(cpuUsagePerPod, k)
bottomKPods := selectBottomK(cpuUsagePerPod, k)

// 3. Calculate averages
currentAvg := average(cpuUsagePerPod)
topKAvg := average(topKPods)
bottomKAvg := average(bottomKPods)
postRotationAvg := average(remainingPods)

// 4. Apply algorithm logic
improvement := abs(currentAvg - targetCPUUsage) - abs(postRotationAvg - targetCPUUsage)
shouldRotate := improvement > improvementThreshold && 
                topKAvg > safetyThreshold && 
                (topKAvg - bottomKAvg) > varianceThreshold
```

This approach keeps PromQL queries simple and maintainable while implementing the sophisticated algorithm logic in Go where it's easier to test and debug.