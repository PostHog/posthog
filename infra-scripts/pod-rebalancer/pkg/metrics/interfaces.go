package metrics

import "context"

// CPUMetricsFetcher defines the interface for fetching CPU-related metrics
type CPUMetricsFetcher interface {
	FetchCPULimits(ctx context.Context) (float64, error)
	FetchCPURequests(ctx context.Context) (float64, error)
	FetchTopKPodsAboveTolerance(
		ctx context.Context, k int, toleranceMultiplier float64, hpaPrefix string,
	) (map[string]float64, error)
	FetchBottomKPods(ctx context.Context, k int) (map[string]float64, error)
}
