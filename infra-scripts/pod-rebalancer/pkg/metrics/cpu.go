package metrics

import (
	"context"
	"fmt"
	"time"

	"github.com/prometheus/common/model"
	"go.uber.org/zap"

	"github.com/posthog/pod-rebalancer/pkg/logging"
)

// PrometheusClient defines the interface for querying Prometheus
type PrometheusClient interface {
	Query(ctx context.Context, query string) (model.Value, error)
}

// CPUMetrics implements the CPUMetricsFetcher interface
type CPUMetrics struct {
	client         PrometheusClient
	logger         *logging.Logger
	namespace      string
	deploymentName string
	timeWindow     time.Duration
}

// NewCPUMetrics creates a new CPU metrics fetcher
func NewCPUMetrics(client PrometheusClient, logger *logging.Logger, namespace, deploymentName string, timeWindow time.Duration) *CPUMetrics {
	return &CPUMetrics{
		client:         client,
		logger:         logger,
		namespace:      namespace,
		deploymentName: deploymentName,
		timeWindow:     timeWindow,
	}
}

// parseCPUResults parses Prometheus query results into a pod->usage map
func (f *CPUMetrics) parseCPUResults(result model.Value) (map[string]float64, error) {
	cpuUsage := make(map[string]float64)

	// Handle different result types
	switch v := result.(type) {
	case model.Vector:
		for _, sample := range v {
			podName, ok := sample.Metric["pod"]
			if !ok {
				f.logger.Warn("CPU metric sample missing pod label", zap.Any("metric", sample.Metric))
				continue
			}

			usage := float64(sample.Value)
			cpuUsage[string(podName)] = usage

			f.logger.Debug("Parsed CPU usage",
				zap.String("pod", string(podName)),
				zap.Float64("cpu_usage", usage),
			)
		}

	case model.Matrix:
		// For range queries, we take the latest value for each pod
		for _, sampleStream := range v {
			podName, ok := sampleStream.Metric["pod"]
			if !ok {
				f.logger.Warn("CPU metric stream missing pod label", zap.Any("metric", sampleStream.Metric))
				continue
			}

			if len(sampleStream.Values) == 0 {
				f.logger.Warn("CPU metric stream has no values", zap.String("pod", string(podName)))
				continue
			}

			// Take the latest value
			latestValue := sampleStream.Values[len(sampleStream.Values)-1]
			usage := float64(latestValue.Value)
			cpuUsage[string(podName)] = usage

			f.logger.Debug("Parsed CPU usage from matrix",
				zap.String("pod", string(podName)),
				zap.Float64("cpu_usage", usage),
				zap.Int("values_count", len(sampleStream.Values)),
			)
		}

	default:
		return nil, fmt.Errorf("unexpected result type from CPU query: %T", v)
	}

	f.logger.Info("Successfully fetched CPU usage metrics",
		zap.Int("pod_count", len(cpuUsage)),
		zap.Any("cpu_usage", cpuUsage),
	)

	return cpuUsage, nil
}

// FetchCPULimits fetches CPU resource limits for containers
// Returns the median CPU limit across containers
func (f *CPUMetrics) FetchCPULimits(ctx context.Context) (float64, error) {
	query := fmt.Sprintf(
		`median(sum(median by (container) (kube_pod_container_resource_limits{resource="cpu", namespace="%s", container="%s"})))`,

		f.namespace, f.deploymentName)

	f.logger.Debug("Executing CPU limits query",
		zap.String("query", query),
		zap.String("namespace", f.namespace),
		zap.String("deployment_name", f.deploymentName),
	)

	result, err := f.client.Query(ctx, query)
	if err != nil {
		f.logger.Error("Failed to query CPU limits", zap.Error(err), zap.String("query", query))
		return 0, fmt.Errorf("failed to query CPU limits: %w", err)
	}

	return f.parseScalarResult(result, "CPU limits")
}

// FetchCPURequests fetches CPU resource requests for containers
// Returns the median CPU request across containers
func (f *CPUMetrics) FetchCPURequests(ctx context.Context) (float64, error) {
	query := fmt.Sprintf(
		`median(sum(median by (container) (kube_pod_container_resource_requests{resource="cpu", namespace="%s", container="%s"})))`,

		f.namespace, f.deploymentName)

	f.logger.Debug("Executing CPU requests query",
		zap.String("query", query),
		zap.String("namespace", f.namespace),
		zap.String("deployment_name", f.deploymentName),
	)

	result, err := f.client.Query(ctx, query)
	if err != nil {
		f.logger.Error("Failed to query CPU requests", zap.Error(err), zap.String("query", query))
		return 0, fmt.Errorf("failed to query CPU requests: %w", err)
	}

	return f.parseScalarResult(result, "CPU requests")
}

// FetchTopKPodsAboveTolerance fetches the top K pods that exceed the tolerance threshold
// This uses a single PromQL query to find pods above HPA target * tolerance multiplier
func (f *CPUMetrics) FetchTopKPodsAboveTolerance(
	ctx context.Context, k int, toleranceMultiplier float64, hpaPrefix string,
) (map[string]float64, error) {
	query := fmt.Sprintf(`topk(%d, sum by(pod) (rate(container_cpu_usage_seconds_total{
  namespace="%s",
  container="%s"
}[%s]))) >
scalar(kube_horizontalpodautoscaler_spec_target_metric{
  horizontalpodautoscaler=~"(%s)?%s",
  namespace="%s",
  metric_name="cpu"
}) / 100 * %.2f *
avg(kube_pod_container_resource_requests{
  resource="cpu",
  namespace="%s",
  container="%s"
})`, k, f.namespace, f.deploymentName, f.timeWindow,
		hpaPrefix, f.deploymentName, f.namespace, toleranceMultiplier,
		f.namespace, f.deploymentName)

	f.logger.Debug("Executing top K pods above tolerance query",
		zap.String("query", query),
		zap.Int("k", k),
		zap.Float64("tolerance_multiplier", toleranceMultiplier),
	)

	result, err := f.client.Query(ctx, query)
	if err != nil {
		f.logger.Error("Failed to query top K pods above tolerance",
			zap.Error(err),
			zap.String("query", query),
		)
		return nil, fmt.Errorf("failed to query top K pods above tolerance: %w", err)
	}

	return f.parseCPUResults(result)
}

// FetchBottomKPods fetches the K pods with lowest CPU usage
func (f *CPUMetrics) FetchBottomKPods(ctx context.Context, k int) (map[string]float64, error) {
	query := fmt.Sprintf(`bottomk(%d, sum by(pod) (rate(container_cpu_usage_seconds_total{
  namespace="%s",
  container="%s"
}[%s])))`, k, f.namespace, f.deploymentName, f.timeWindow)

	f.logger.Debug("Executing bottom K pods query",
		zap.String("query", query),
		zap.Int("k", k),
	)

	result, err := f.client.Query(ctx, query)
	if err != nil {
		f.logger.Error("Failed to query bottom K pods",
			zap.Error(err),
			zap.String("query", query),
		)
		return nil, fmt.Errorf("failed to query bottom K pods: %w", err)
	}

	return f.parseCPUResults(result)
}

// parseScalarResult parses a scalar result from Prometheus
func (f *CPUMetrics) parseScalarResult(result model.Value, metricName string) (float64, error) {
	switch v := result.(type) {
	case model.Vector:
		if len(v) == 0 {
			f.logger.Warn("No data returned for metric", zap.String("metric", metricName))
			return 0, nil
		}
		// Take the first (and likely only) value
		value := float64(v[0].Value)
		f.logger.Debug("Parsed scalar metric",
			zap.String("metric", metricName),
			zap.Float64("value", value),
		)
		return value, nil

	case *model.Scalar:
		value := float64(v.Value)
		f.logger.Debug("Parsed scalar metric",
			zap.String("metric", metricName),
			zap.Float64("value", value),
		)
		return value, nil

	default:
		return 0, fmt.Errorf("unexpected result type for %s query: %T", metricName, v)
	}
}
