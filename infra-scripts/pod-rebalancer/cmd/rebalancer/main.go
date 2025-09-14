package main

import (
	"context"
	"fmt"
	"os"
	"time"

	"go.uber.org/zap"

	"github.com/posthog/pod-rebalancer/pkg/config"
	"github.com/posthog/pod-rebalancer/pkg/decision"
	"github.com/posthog/pod-rebalancer/pkg/kubernetes"
	"github.com/posthog/pod-rebalancer/pkg/metrics"
	"github.com/posthog/pod-rebalancer/pkg/prometheus"
)

func main() {
	ctx := context.Background()
	
	// 1. Load configuration from environment using Viper
	cfg, err := config.LoadFromEnv()
	if err != nil {
		fmt.Printf("Failed to load configuration: %v\n", err)
		os.Exit(1)
	}
	
	// 2. Create zap logger with configured level
	logger, err := createLogger(cfg.LogLevel)
	if err != nil {
		fmt.Printf("Failed to create logger: %v\n", err)
		os.Exit(1)
	}
	defer logger.Sync()
	
	logger.Info("Starting Pod Rebalancer",
		zap.String("version", "v0.1.0"),
		zap.String("namespace", cfg.KubeNamespace),
		zap.String("deployment", cfg.DeploymentName),
		zap.Bool("dry_run", cfg.DryRun))
	
	// 3. Create Prometheus HTTP client
	promClient, err := prometheus.NewClient(cfg.PrometheusEndpoint, cfg.PrometheusTimeout)
	if err != nil {
		logger.Fatal("Failed to create Prometheus client", zap.Error(err))
	}
	
	// 4. Create CPU metrics fetcher with specialized queries
	cpuMetrics := metrics.NewCPUMetrics(
		promClient, logger, 
		cfg.KubeNamespace, cfg.DeploymentName, cfg.MetricsTimeWindow,
	)
	
	// 5. Create HPA-aware decision engine (no aggregator needed)
	engine := decision.NewEngine(
		cpuMetrics, cfg.RebalanceTopKPods, cfg.ToleranceMultiplier,
		cfg.MinimumImprovementPercent, cfg.HPAPrefix, logger,
	)
	
	// 6. Execute sophisticated rebalancing analysis
	logger.Info("Starting rebalancing analysis")
	start := time.Now()
	
	analysis, err := engine.Analyze(ctx)
	if err != nil {
		logger.Fatal("Failed to analyze pods for rebalancing", zap.Error(err))
	}
	
	duration := time.Since(start)
	logger.Info("Analysis completed",
		zap.Duration("duration", duration),
		zap.Bool("should_rebalance", analysis.ShouldRebalance),
		zap.String("reason", analysis.Reason))
	
	// 7. Execute deletions if improvement exceeds minimum threshold
	if analysis.ShouldRebalance {
		logger.Info("Rebalancing required, proceeding with pod deletions",
			zap.Strings("target_pods", analysis.TargetPods),
			zap.Float64("improvement_percent", analysis.Metrics.ImprovementPercent))
		
		// Create Kubernetes manager
		k8sManager, err := kubernetes.NewManager(cfg.KubeNamespace, cfg.DryRun, logger)
		if err != nil {
			logger.Fatal("Failed to create Kubernetes manager", zap.Error(err))
		}
		
		// Validate minimum pod count before deletion
		err = k8sManager.ValidateMinimumPods(ctx, analysis.TargetPods, cfg.KubeLabelSelector, cfg.MinimumPodsRequired)
		if err != nil {
			logger.Fatal("Minimum pod validation failed", zap.Error(err))
		}
		
		// Execute pod deletions
		result, err := k8sManager.DeletePods(ctx, analysis.TargetPods)
		if err != nil {
			logger.Fatal("Failed to delete pods", zap.Error(err))
		}
		
		// Log detailed results
		logger.Info("Pod deletion completed",
			zap.Int("attempted", len(result.Attempted)),
			zap.Int("deleted", len(result.Deleted)),
			zap.Int("skipped", len(result.Skipped)),
			zap.Int("errors", len(result.Errors)),
			zap.Strings("deleted_pods", result.Deleted))
		
		if len(result.Errors) > 0 {
			logger.Error("Some pod deletions failed")
			for pod, err := range result.Errors {
				logger.Error("Pod deletion error", zap.String("pod", pod), zap.Error(err))
			}
			os.Exit(1)
		}
		
		logger.Info("Rebalancing completed successfully",
			zap.Float64("improvement_percent", analysis.Metrics.ImprovementPercent),
			zap.Duration("total_duration", time.Since(start)))
	} else {
		logger.Info("No rebalancing needed",
			zap.String("reason", analysis.Reason),
			zap.Float64("improvement_percent", analysis.Metrics.ImprovementPercent),
			zap.Int("filtered_top_pods", len(analysis.FilteredTopPods)),
			zap.Int("bottom_pods", len(analysis.BottomPods)))
	}
	
	logger.Info("Pod rebalancer completed successfully", zap.Duration("total_duration", time.Since(start)))
}

// createLogger creates a zap logger with the specified level
func createLogger(level string) (*zap.Logger, error) {
	var zapLevel zap.AtomicLevel
	switch level {
	case "debug":
		zapLevel = zap.NewAtomicLevelAt(zap.DebugLevel)
	case "info":
		zapLevel = zap.NewAtomicLevelAt(zap.InfoLevel)
	case "warn":
		zapLevel = zap.NewAtomicLevelAt(zap.WarnLevel)
	case "error":
		zapLevel = zap.NewAtomicLevelAt(zap.ErrorLevel)
	default:
		zapLevel = zap.NewAtomicLevelAt(zap.InfoLevel)
	}
	
	config := zap.Config{
		Level:            zapLevel,
		Development:      false,
		Encoding:         "json",
		EncoderConfig:    zap.NewProductionEncoderConfig(),
		OutputPaths:      []string{"stdout"},
		ErrorOutputPaths: []string{"stderr"},
	}
	
	return config.Build()
}
