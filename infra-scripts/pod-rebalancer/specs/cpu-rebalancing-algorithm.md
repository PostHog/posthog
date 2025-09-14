# CPU Rebalancing Algorithm - HPA-Aware Pod Rotation

## Overview

An intelligent pod rotation algorithm that identifies CPU outliers above a tolerance threshold and only rotates pods when it will provide meaningful improvement to the overall CPU distribution.

## Algorithm Steps

### 1. **Data Collection**
- Fetch HPA target utilization percentage (0-100)
- Fetch per-pod CPU usage rates
- Fetch per-pod CPU requests (average across all pods)
- Calculate target CPU usage: `target_cpu_usage = hpa_target_utilization_percent / 100 * avg_cpu_request`

### 2. **Identify Candidate Pods**
```
top_k_candidates = topk(K, cpu_usage_per_pod)
bottom_k_candidates = bottomk(K, cpu_usage_per_pod)
```
Where K is configurable (default: 2)

### 3. **Apply Tolerance Filter**
```
tolerance_threshold = target_cpu_usage * tolerance_multiplier
# Only consider top pods that are actually problematic
filtered_top_k_pods = top_k_candidates where cpu_usage > tolerance_threshold
```
Where tolerance_multiplier is configurable (default: 1.5 = 150% of target)

### 4. **Calculate Improvement Potential**
```
# Current state
current_avg_top_bottom = average(filtered_top_k_pods + bottom_k_candidates)
current_avg_top_only = average(filtered_top_k_pods)

# Calculate potential improvement
improvement_absolute = current_avg_top_only - current_avg_top_bottom
improvement_percentage = improvement_absolute / current_avg_top_only * 100
```

### 5. **Decision Logic**
```
minimum_improvement_percent = configurable (default: 10%)

should_rotate = (
    len(filtered_top_k_pods) > 0 AND
    improvement_percentage > minimum_improvement_percent
)

if should_rotate:
    pods_to_delete = filtered_top_k_pods + bottom_k_candidates
else:
    reason = determine_skip_reason()
```

### 6. **Execution Decision**
```
if should_rotate:
    delete filtered_top_k_pods + bottom_k_candidates
    log improvement metrics and selected pods
else:
    log why rotation was skipped (no problematic pods, insufficient improvement, etc.)
```

## Configuration Parameters

```bash
# Algorithm parameters
REBALANCE_TOP_K_PODS=2                    # Number of top/bottom candidate pods to consider
TOLERANCE_MULTIPLIER=1.5                 # Only act on top pods above this threshold (150% of target)
MINIMUM_IMPROVEMENT_PERCENT=10            # Minimum improvement required (% of top pod average CPU)

# HPA detection (optional prefix)
HPA_PREFIX=keda-hpa                       # Optional prefix for HPA name
HPA_METRIC_NAME=cpu                       # Metric name filter

# Future: Kafka lag condition detection
KAFKA_LAG_THRESHOLD=1000                  # Lag threshold to enable/disable rebalancing
KAFKA_LAG_ENABLED=false                   # Enable Kafka lag-based conditions (v2)
```

## Example Scenario

**Given:**
- HPA target: 70% CPU utilization
- CPU request: 1.0 cores per pod (average)
- Target CPU usage: 0.7 cores
- Tolerance multiplier: 1.5 (tolerance threshold = 1.05 cores)
- Minimum improvement: 10%

**Current state:**
- Pod A: 1.2 cores (171% of request) 
- Pod B: 1.1 cores (157% of request)
- Pod C: 0.8 cores (114% of request)
- Pod D: 0.6 cores (86% of request)
- Pod E: 0.4 cores (57% of request)
- Pod F: 0.3 cores (43% of request)

**Analysis:**
1. **Top 2 candidates**: Pod A (1.2), Pod B (1.1)
2. **Bottom 2 candidates**: Pod F (0.3), Pod E (0.4)
3. **Apply tolerance filter**: Pod A (1.2 > 1.05 ✓), Pod B (1.1 > 1.05 ✓)
4. **Filtered top pods**: Pod A, Pod B
5. **Calculate improvement**:
   - Current avg top+bottom: (1.2 + 1.1 + 0.3 + 0.4) / 4 = 0.75 cores
   - Current avg top only: (1.2 + 1.1) / 2 = 1.15 cores
   - Improvement: 1.15 - 0.75 = 0.4 cores
   - Improvement percentage: 0.4 / 1.15 * 100 = 34.8%

**Decision:**
- Filtered top pods exist: ✓ (Pod A, Pod B)
- Improvement (34.8%) > minimum (10%): ✓
- **Result: ROTATE** - Delete Pod A, Pod B, Pod E, Pod F

## Benefits

1. **Tolerance-Based**: Only acts on pods that are truly problematic (above tolerance threshold)
2. **Improvement-Driven**: Only rotates when meaningful improvement is guaranteed
3. **HPA-Aligned**: Uses the same target utilization as the HPA system
4. **Measurable**: Quantifies expected improvement percentage before acting
5. **Configurable**: Tunable thresholds for different workload patterns
6. **Future-Ready**: Designed to integrate Kafka lag conditions in iteration 2

## Monitoring Metrics

```promql
# Key metrics to track algorithm performance
rebalancer_current_cpu_average
rebalancer_predicted_cpu_average  
rebalancer_improvement_calculated
rebalancer_safety_threshold_current
rebalancer_rotation_decisions_total{reason}
```

This algorithm ensures pod rotation only occurs when it will meaningfully improve CPU distribution toward the HPA target, with robust safety mechanisms to prevent unnecessary disruption.