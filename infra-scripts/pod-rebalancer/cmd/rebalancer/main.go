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
	"github.com/posthog/pod-rebalancer/pkg/logging"
	"github.com/posthog/pod-rebalancer/pkg/metrics"
	"github.com/posthog/pod-rebalancer/pkg/prometheus"
)

func main() {
	if len(os.Args) > 1 {
		switch os.Args[1] {
		case "--help", "-h":
			printHelp()
			os.Exit(0)
		}
	}

	ctx := context.Background()

	cfg, err := config.LoadFromEnv()
	if err != nil {
		fmt.Printf("Failed to load configuration: %v\n", err)
		os.Exit(1)
	}

	logger, err := logging.New(cfg.LogLevel)
	if err != nil {
		fmt.Printf("Failed to create logger: %v\n", err)
		os.Exit(1)
	}
	defer func() {
		_ = logger.Sync()
	}()

	logger.Info("Starting Pod Rebalancer",
		zap.String("namespace", cfg.KubeNamespace),
		zap.String("deployment", cfg.DeploymentName),
		zap.Bool("dry_run", cfg.DryRun))

	promClient, err := prometheus.NewClient(cfg.PrometheusEndpoint, cfg.PrometheusTimeout, logger)
	if err != nil {
		logger.Error("Failed to create Prometheus client", zap.Error(err))
		os.Exit(1)
	}

	cpuMetrics := metrics.NewCPUMetrics(
		promClient, logger,
		cfg.KubeNamespace, cfg.DeploymentName, cfg.MetricsTimeWindow,
	)

	engine := decision.NewEngine(
		cpuMetrics, cfg.RebalanceTopKPods, cfg.ToleranceMultiplier,
		cfg.MinimumImprovementPercent, cfg.HPAPrefix, logger,
	)

	logger.Info("Starting rebalancing analysis")
	start := time.Now()

	analysis, err := engine.Analyze(ctx)
	if err != nil {
		logger.Error("Failed to analyze pods for rebalancing", zap.Error(err))
		os.Exit(1)
	}

	duration := time.Since(start)
	logger.Info("Analysis completed",
		zap.Duration("duration", duration),
		zap.Bool("should_rebalance", analysis.ShouldRebalance),
		zap.String("reason", analysis.Reason))

	if analysis.ShouldRebalance {
		err = executeRebalancing(ctx, cfg, analysis, logger, start)
		if err != nil {
			logger.Error("Rebalancing failed", zap.Error(err))
			os.Exit(1)
		}
	} else {
		logger.Info("No rebalancing needed",
			zap.String("reason", analysis.Reason),
			zap.Float64("improvement_percent", analysis.Metrics.ImprovementPercent),
			zap.Int("filtered_top_pods", len(analysis.FilteredTopPods)),
			zap.Int("bottom_pods", len(analysis.BottomPods)))
	}

	logger.Info("Pod rebalancer completed successfully", zap.Duration("total_duration", time.Since(start)))
}

func executeRebalancing(
	ctx context.Context, cfg *config.Config, analysis *decision.Analysis,
	logger *logging.Logger, start time.Time,
) error {
	logger.Info("Rebalancing required, proceeding with pod deletions",
		zap.Strings("target_pods", analysis.TargetPods),
		zap.Float64("improvement_percent", analysis.Metrics.ImprovementPercent))

	k8sManager, err := kubernetes.NewManager(cfg.KubeNamespace, cfg.DryRun, logger)
	if err != nil {
		return fmt.Errorf("failed to create Kubernetes manager: %w", err)
	}

	err = k8sManager.ValidateMinimumPods(ctx, analysis.TargetPods, cfg.KubeLabelSelector, cfg.MinimumPodsRequired)
	if err != nil {
		return fmt.Errorf("minimum pod validation failed: %w", err)
	}

	result, err := k8sManager.DeletePods(ctx, analysis.TargetPods)
	if err != nil {
		return fmt.Errorf("failed to delete pods: %w", err)
	}

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
		return fmt.Errorf("pod deletion errors occurred")
	}

	logger.Info("Rebalancing completed successfully",
		zap.Float64("improvement_percent", analysis.Metrics.ImprovementPercent),
		zap.Duration("total_duration", time.Since(start)))

	return nil
}

func printHelp() {
	fmt.Println("PostHog Pod Rebalancer")
	fmt.Println("HPA-aware Kafka consumer pod rebalancer")
	fmt.Println()
	fmt.Println("USAGE:")
	fmt.Println("  pod-rebalancer [OPTIONS]")
	fmt.Println()
	fmt.Println("OPTIONS:")
	fmt.Println("  -h, --help     Show this help message")
	fmt.Println()
	fmt.Println("CONFIGURATION (Environment Variables):")
	fmt.Println("  Required:")
	fmt.Println("    DEPLOYMENT_NAME              Container name for metrics queries (required)")
	fmt.Println("  ")
	fmt.Println("  Optional:")
	fmt.Println("    PROMETHEUS_ENDPOINT          Prometheus/VictoriaMetrics endpoint (default: http://localhost:9090)")
	fmt.Println("    PROMETHEUS_TIMEOUT           Query timeout (default: 30s)")
	fmt.Println("    KUBE_NAMESPACE               Kubernetes namespace (default: posthog)")
	fmt.Println("    KUBE_LABEL_SELECTOR          Pod label selector (default: app=consumer)")
	fmt.Println("    METRICS_TIME_WINDOW          Time window for CPU rate calculations (default: 5m)")
	fmt.Println("    REBALANCE_TOP_K_PODS         Number of top/bottom pods to consider (default: 2)")
	fmt.Println("    TOLERANCE_MULTIPLIER         HPA target threshold multiplier (default: 1.5)")
	fmt.Println("    MINIMUM_IMPROVEMENT_PERCENT  Required improvement percentage (default: 10.0)")
	fmt.Println("    MINIMUM_PODS_REQUIRED        Minimum pods to maintain after deletion (default: 2)")
	fmt.Println("    HPA_PREFIX                   HPA name prefix (default: \"keda-hpa-\")")
	fmt.Println("    DRY_RUN                      Enable dry-run mode (default: false)")
	fmt.Println("    LOG_LEVEL                    Logging level: debug,info,warn,error (default: info)")
	fmt.Println()
	fmt.Println("EXAMPLES:")
	fmt.Println("  # Production run")
	fmt.Println("  DEPLOYMENT_NAME=ingestion-events ./pod-rebalancer")
	fmt.Println()
	fmt.Println("  # Dry run with debug logging")
	fmt.Println("  DRY_RUN=true LOG_LEVEL=debug DEPLOYMENT_NAME=ingestion-events ./pod-rebalancer")
	fmt.Println()
	fmt.Println("For more information, visit: https://github.com/PostHog/posthog")
}
