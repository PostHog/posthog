package config

import (
	"fmt"
	"time"

	"github.com/spf13/viper"
)

// Config represents the complete application configuration loaded from environment variables
type Config struct {
	// Prometheus/VictoriaMetrics configuration
	PrometheusEndpoint string
	PrometheusTimeout  time.Duration

	// Kubernetes configuration
	KubeNamespace     string
	KubeLabelSelector string
	DeploymentName    string // Container name for metrics queries (literal match)

	// Metrics configuration
	MetricsTimeWindow time.Duration // Time window for rate calculations

	// Decision making parameters
	RebalanceTopKPods        int     // Number of top/bottom pods to consider
	ToleranceMultiplier      float64 // Only act on pods above this threshold (multiplier of HPA target)
	MinimumImprovementPercent float64 // Minimum improvement required (% of top pod average CPU)
	HPAPrefix                string  // Optional prefix for HPA name (e.g., "keda-hpa-")

	// Safety and debugging
	MinimumPodsRequired int  // Minimum pods that must remain after deletion
	DryRun              bool
	LogLevel            string
}

// LoadFromEnv loads configuration from environment variables with defaults using Viper
func LoadFromEnv() (*Config, error) {
	v := viper.New()

	// Set defaults
	v.SetDefault("PROMETHEUS_ENDPOINT", "http://localhost:9090")
	v.SetDefault("PROMETHEUS_TIMEOUT", "30s")
	v.SetDefault("KUBE_NAMESPACE", "posthog")
	v.SetDefault("KUBE_LABEL_SELECTOR", "app=consumer")
	// DEPLOYMENT_NAME has no default - must be explicitly configured
	v.SetDefault("METRICS_TIME_WINDOW", "5m")
	v.SetDefault("REBALANCE_TOP_K_PODS", 2)
	v.SetDefault("TOLERANCE_MULTIPLIER", 1.5)
	v.SetDefault("MINIMUM_IMPROVEMENT_PERCENT", 10.0)
	v.SetDefault("HPA_PREFIX", "keda-hpa-")
	v.SetDefault("MINIMUM_PODS_REQUIRED", 2)
	v.SetDefault("DRY_RUN", false)
	v.SetDefault("LOG_LEVEL", "info")

	// Configure environment variable handling
	v.AutomaticEnv()

	// Parse timeout duration - Viper doesn't handle time.Duration automatically
	timeoutStr := v.GetString("PROMETHEUS_TIMEOUT")
	timeout, err := time.ParseDuration(timeoutStr)
	if err != nil {
		return nil, fmt.Errorf("invalid PROMETHEUS_TIMEOUT: %w", err)
	}

	// Parse metrics time window
	timeWindowStr := v.GetString("METRICS_TIME_WINDOW")
	timeWindow, err := time.ParseDuration(timeWindowStr)
	if err != nil {
		return nil, fmt.Errorf("invalid METRICS_TIME_WINDOW: %w", err)
	}

	config := &Config{
		PrometheusEndpoint:        v.GetString("PROMETHEUS_ENDPOINT"),
		PrometheusTimeout:         timeout,
		KubeNamespace:             v.GetString("KUBE_NAMESPACE"),
		KubeLabelSelector:         v.GetString("KUBE_LABEL_SELECTOR"),
		DeploymentName:            v.GetString("DEPLOYMENT_NAME"),
		MetricsTimeWindow:         timeWindow,
		RebalanceTopKPods:         v.GetInt("REBALANCE_TOP_K_PODS"),
		ToleranceMultiplier:       v.GetFloat64("TOLERANCE_MULTIPLIER"),
		MinimumImprovementPercent: v.GetFloat64("MINIMUM_IMPROVEMENT_PERCENT"),
		HPAPrefix:                 v.GetString("HPA_PREFIX"),
		MinimumPodsRequired:       v.GetInt("MINIMUM_PODS_REQUIRED"),
		DryRun:                    v.GetBool("DRY_RUN"),
		LogLevel:                  v.GetString("LOG_LEVEL"),
	}

	// Validate the configuration after Viper parsing
	if err := config.Validate(); err != nil {
		return nil, fmt.Errorf("configuration validation failed: %w", err)
	}

	return config, nil
}

// Validate checks if the configuration is valid
func (c *Config) Validate() error {
	if c.PrometheusEndpoint == "" {
		return fmt.Errorf("PROMETHEUS_ENDPOINT is required")
	}

	if c.PrometheusTimeout <= 0 {
		return fmt.Errorf("PROMETHEUS_TIMEOUT must be positive")
	}

	if c.KubeNamespace == "" {
		return fmt.Errorf("KUBE_NAMESPACE is required")
	}

	if c.KubeLabelSelector == "" {
		return fmt.Errorf("KUBE_LABEL_SELECTOR is required")
	}

	if c.DeploymentName == "" {
		return fmt.Errorf("DEPLOYMENT_NAME is required")
	}

	if c.RebalanceTopKPods < 1 {
		return fmt.Errorf("REBALANCE_TOP_K_PODS must be at least 1")
	}

	if c.ToleranceMultiplier < 1.0 {
		return fmt.Errorf("TOLERANCE_MULTIPLIER must be at least 1.0")
	}

	if c.MinimumImprovementPercent < 0 || c.MinimumImprovementPercent > 100 {
		return fmt.Errorf("MINIMUM_IMPROVEMENT_PERCENT must be between 0 and 100")
	}

	if c.MinimumPodsRequired < 1 {
		return fmt.Errorf("MINIMUM_PODS_REQUIRED must be at least 1")
	}

	// Validate log level
	validLogLevels := []string{"debug", "info", "warn", "error"}
	isValidLogLevel := false
	for _, level := range validLogLevels {
		if c.LogLevel == level {
			isValidLogLevel = true
			break
		}
	}
	if !isValidLogLevel {
		return fmt.Errorf("LOG_LEVEL must be one of: debug, info, warn, error")
	}

	return nil
}
