package main

import (
	"context"
	"fmt"
	"log"
	"time"

	"github.com/posthog/pod-rebalancer/pkg/metrics"
	"github.com/posthog/pod-rebalancer/pkg/prometheus"
	"go.uber.org/zap"
)

func main() {
	// This example demonstrates how to use the Prometheus client and CPU metrics fetcher
	fmt.Println("Pod Rebalancer - CPU Metrics Example")

	// Create a logger
	logger, err := zap.NewDevelopment()
	if err != nil {
		log.Fatal("Failed to create logger:", err)
	}
	defer logger.Sync()

	// Configuration (would normally come from environment)
	prometheusEndpoint := "http://localhost:9090" // Change to your VictoriaMetrics/Prometheus endpoint
	timeout := 30 * time.Second
	namespace := "posthog"            // Kubernetes namespace
	deploymentName := "ingestion-.*"  // Container name pattern to match

	// Create Prometheus client
	client, err := prometheus.NewClient(prometheusEndpoint, timeout)
	if err != nil {
		logger.Fatal("Failed to create Prometheus client", zap.Error(err))
	}

	// Test connectivity
	ctx := context.Background()
	logger.Info("Testing Prometheus connectivity...")
	if err := client.IsHealthy(ctx); err != nil {
		logger.Error("Prometheus health check failed", zap.Error(err))
		logger.Info("Make sure Prometheus/VictoriaMetrics is running at", zap.String("endpoint", prometheusEndpoint))
		return
	}
	logger.Info("✓ Connected to Prometheus successfully")

	// Create CPU metrics fetcher
	timeWindow := time.Minute // Configurable time window for rate calculations
	cpuFetcher := metrics.NewCPUMetricsFetcher(client, logger, namespace, deploymentName, timeWindow)

	// Fetch CPU usage for pods
	logger.Info("Fetching CPU metrics...", 
		zap.String("namespace", namespace),
		zap.String("deployment_name", deploymentName))
	cpuUsage, err := cpuFetcher.FetchCPUUsage(ctx)
	if err != nil {
		logger.Error("Failed to fetch CPU metrics", zap.Error(err))
		return
	}

	// Display results
	if len(cpuUsage) == 0 {
		logger.Warn("No pods found matching deployment", 
			zap.String("namespace", namespace),
			zap.String("deployment_name", deploymentName))
		logger.Info("Make sure your pods are running and have CPU metrics available")
		return
	}

	logger.Info("CPU Usage Results", zap.Int("pod_count", len(cpuUsage)))
	for podName, usage := range cpuUsage {
		logger.Info("Pod CPU usage",
			zap.String("pod", podName),
			zap.Float64("cpu_cores", usage),
			zap.String("cpu_percentage", fmt.Sprintf("%.1f%%", usage*100)),
		)
	}

	// Example analysis (this would be part of the decision engine)
	logger.Info("Example Analysis:")
	var totalCPU float64
	var highUsagePods []string
	var lowUsagePods []string

	for podName, usage := range cpuUsage {
		totalCPU += usage
		if usage > 0.5 { // 50% CPU usage threshold
			highUsagePods = append(highUsagePods, podName)
		} else if usage < 0.1 { // 10% CPU usage threshold
			lowUsagePods = append(lowUsagePods, podName)
		}
	}

	avgCPU := totalCPU / float64(len(cpuUsage))
	
	logger.Info("CPU Analysis Summary",
		zap.Float64("average_cpu", avgCPU),
		zap.Float64("total_cpu", totalCPU),
		zap.Strings("high_usage_pods", highUsagePods),
		zap.Strings("low_usage_pods", lowUsagePods),
	)

	if len(highUsagePods) > 0 && len(lowUsagePods) > 0 {
		logger.Info("🔄 Rebalancing recommendation: Consider redistributing load",
			zap.Int("high_usage_count", len(highUsagePods)),
			zap.Int("low_usage_count", len(lowUsagePods)),
		)
	} else {
		logger.Info("✓ CPU usage appears balanced")
	}
}