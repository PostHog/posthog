package metrics

import (
	"context"
	"fmt"
	"time"

	"github.com/prometheus/common/model"
	"go.uber.org/zap"
)

// PrometheusClient defines the interface for querying Prometheus
type PrometheusClient interface {
	Query(ctx context.Context, query string) (model.Value, error)
}

// CPUMetricsFetcher fetches CPU usage metrics for pods
type CPUMetricsFetcher struct {
	client         PrometheusClient
	logger         *zap.Logger
	namespace      string
	deploymentName string
	timeWindow     time.Duration
}

// NewCPUMetricsFetcher creates a new CPU metrics fetcher
func NewCPUMetricsFetcher(client PrometheusClient, logger *zap.Logger, namespace, deploymentName string, timeWindow time.Duration) *CPUMetricsFetcher {
	return &CPUMetricsFetcher{
		client:         client,
		logger:         logger,
		namespace:      namespace,
		deploymentName: deploymentName,
		timeWindow:     timeWindow,
	}
}

// FetchCPUUsage fetches CPU usage metrics for pods matching the deployment
// Returns a map of pod name to CPU usage rate (cores per second)
func (f *CPUMetricsFetcher) FetchCPUUsage(ctx context.Context) (map[string]float64, error) {
	// PromQL query to get CPU usage rate per pod, using literal container match
	query := fmt.Sprintf(`sum by(pod) (rate(container_cpu_usage_seconds_total{namespace="%s", container="%s"}[%s]))`, 
		f.namespace, f.deploymentName, f.timeWindow)
	
	f.logger.Debug("Executing CPU metrics query",
		zap.String("query", query),
		zap.String("namespace", f.namespace),
		zap.String("deployment_name", f.deploymentName),
		zap.Duration("time_window", f.timeWindow),
	)

	result, err := f.client.Query(ctx, query)
	if err != nil {
		f.logger.Error("Failed to query CPU metrics",
			zap.Error(err),
			zap.String("query", query),
		)
		return nil, fmt.Errorf("failed to query CPU metrics: %w", err)
	}

	return f.parseCPUResults(result)
}

// parseCPUResults parses Prometheus query results into a pod->usage map
func (f *CPUMetricsFetcher) parseCPUResults(result model.Value) (map[string]float64, error) {
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
func (f *CPUMetricsFetcher) FetchCPULimits(ctx context.Context) (float64, error) {
	query := fmt.Sprintf(`median(sum(median by (container) (kube_pod_container_resource_limits{resource="cpu", namespace="%s", container="%s"})))`,
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
func (f *CPUMetricsFetcher) FetchCPURequests(ctx context.Context) (float64, error) {
	query := fmt.Sprintf(`median(sum(median by (container) (kube_pod_container_resource_requests{resource="cpu", namespace="%s", container="%s"})))`,
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


// parseScalarResult parses a scalar result from Prometheus
func (f *CPUMetricsFetcher) parseScalarResult(result model.Value, metricName string) (float64, error) {
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