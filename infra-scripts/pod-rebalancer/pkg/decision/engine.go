package decision

import (
	"context"
	"fmt"
	"math"

	"go.uber.org/zap"

	"github.com/posthog/pod-rebalancer/pkg/logging"
	"github.com/posthog/pod-rebalancer/pkg/metrics"
)

// Engine analyzes CPU usage and selects pods for deletion based on the sophisticated algorithm
type Engine struct {
	cpuFetcher                metrics.CPUMetricsFetcher
	topKPods                  int
	toleranceMultiplier       float64
	minimumImprovementPercent float64
	hpaPrefix                 string
	logger                    *logging.Logger
}

// NewEngine creates a new decision engine with the specified parameters
func NewEngine(cpuFetcher metrics.CPUMetricsFetcher, topK int, toleranceMultiplier, minimumImprovementPercent float64, hpaPrefix string, logger *logging.Logger) *Engine {
	return &Engine{
		cpuFetcher:                cpuFetcher,
		topKPods:                  topK,
		toleranceMultiplier:       toleranceMultiplier,
		minimumImprovementPercent: minimumImprovementPercent,
		hpaPrefix:                 hpaPrefix,
		logger:                    logger,
	}
}

// Analysis contains the CPU-based decision results
type Analysis struct {
	ShouldRebalance bool
	TargetPods      []string
	FilteredTopPods map[string]float64
	BottomPods      map[string]float64
	Reason          string
	Metrics         AnalysisMetrics
}

// AnalysisMetrics contains detailed metrics about the analysis
type AnalysisMetrics struct {
	CurrentAvgTopBottom float64
	CurrentAvgTopOnly   float64
	ImprovementAbsolute float64
	ImprovementPercent  float64
}

// Analyze implements the sophisticated HPA-aware algorithm using two PromQL queries
func (e *Engine) Analyze(ctx context.Context) (*Analysis, error) {
	// Initialize analysis
	analysis := &Analysis{}

	// Query 1: Get top K pods that exceed tolerance threshold
	filteredTopPods, err := e.cpuFetcher.FetchTopKPodsAboveTolerance(ctx, e.topKPods, e.toleranceMultiplier, e.hpaPrefix)
	if err != nil {
		return nil, fmt.Errorf("failed to fetch top K pods above tolerance: %w", err)
	}
	analysis.FilteredTopPods = filteredTopPods

	// If no pods exceed tolerance, no rebalancing needed
	if len(filteredTopPods) == 0 {
		analysis.ShouldRebalance = false
		analysis.Reason = fmt.Sprintf("No pods exceed tolerance threshold (%.1fx of HPA target)", e.toleranceMultiplier)
		e.logAnalysis(analysis)
		return analysis, nil
	}

	// Query 2: Get bottom K pods
	bottomPods, err := e.cpuFetcher.FetchBottomKPods(ctx, e.topKPods)
	if err != nil {
		return nil, fmt.Errorf("failed to fetch bottom K pods: %w", err)
	}
	analysis.BottomPods = bottomPods

	// Calculate averages
	avgTopOnly := e.calculateAverage(filteredTopPods)

	// Combine top and bottom pods for combined average
	combinedPods := make(map[string]float64)
	for k, v := range filteredTopPods {
		combinedPods[k] = v
	}
	for k, v := range bottomPods {
		combinedPods[k] = v
	}
	avgTopBottom := e.calculateAverage(combinedPods)

	analysis.Metrics.CurrentAvgTopOnly = avgTopOnly
	analysis.Metrics.CurrentAvgTopBottom = avgTopBottom
	analysis.Metrics.ImprovementAbsolute = avgTopOnly - avgTopBottom
	analysis.Metrics.ImprovementPercent = (analysis.Metrics.ImprovementAbsolute / avgTopOnly) * 100

	// Make decision
	if analysis.Metrics.ImprovementPercent > e.minimumImprovementPercent {
		analysis.ShouldRebalance = true
		analysis.Reason = fmt.Sprintf("Improvement %.1f%% exceeds minimum %.1f%%",
			analysis.Metrics.ImprovementPercent, e.minimumImprovementPercent)

		// Build target pod list
		for podName := range filteredTopPods {
			analysis.TargetPods = append(analysis.TargetPods, podName)
		}
		for podName := range bottomPods {
			analysis.TargetPods = append(analysis.TargetPods, podName)
		}
	} else {
		analysis.ShouldRebalance = false
		analysis.Reason = fmt.Sprintf("Improvement %.1f%% below minimum %.1f%%",
			analysis.Metrics.ImprovementPercent, e.minimumImprovementPercent)
	}

	e.logAnalysis(analysis)
	return analysis, nil
}

// calculateAverage computes the average CPU usage from a map
func (e *Engine) calculateAverage(pods map[string]float64) float64 {
	if len(pods) == 0 {
		return 0
	}

	sum := 0.0
	for _, cpu := range pods {
		sum += cpu
	}
	return sum / float64(len(pods))
}

// logAnalysis logs detailed analysis results
func (e *Engine) logAnalysis(analysis *Analysis) {
	e.logger.Info("CPU rebalancing analysis completed",
		zap.Bool("should_rebalance", analysis.ShouldRebalance),
		zap.String("reason", analysis.Reason),
		zap.Int("filtered_top_pods", len(analysis.FilteredTopPods)),
		zap.Int("bottom_pods", len(analysis.BottomPods)),
		zap.Float64("avg_top_only", analysis.Metrics.CurrentAvgTopOnly),
		zap.Float64("avg_top_bottom", analysis.Metrics.CurrentAvgTopBottom),
		zap.Float64("improvement_percent", math.Round(analysis.Metrics.ImprovementPercent*10)/10),
		zap.Strings("target_pods", analysis.TargetPods),
	)
}
