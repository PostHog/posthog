package config

import (
	"fmt"
	"os"
	"strconv"
	"time"
)

// Config represents the complete application configuration loaded from environment variables
type Config struct {
	// Prometheus/VictoriaMetrics configuration
	PrometheusEndpoint string
	PrometheusTimeout  time.Duration

	// Kubernetes configuration
	KubeNamespace     string
	KubeLabelSelector string

	// Decision making thresholds
	CPUVarianceThreshold float64
	LagVarianceThreshold float64
	MinPodsRequired      int

	// Safety and debugging
	DryRun   bool
	LogLevel string
}

// LoadFromEnv loads configuration from environment variables with defaults
func LoadFromEnv() (*Config, error) {
	config := &Config{
		// Default values
		PrometheusEndpoint:   "http://localhost:9090",
		PrometheusTimeout:    30 * time.Second,
		KubeNamespace:        "default",
		KubeLabelSelector:    "app=consumer",
		CPUVarianceThreshold: 0.3,
		LagVarianceThreshold: 0.5,
		MinPodsRequired:      3,
		DryRun:               false,
		LogLevel:             "info",
	}

	// Load values from environment variables
	if endpoint := os.Getenv("PROMETHEUS_ENDPOINT"); endpoint != "" {
		config.PrometheusEndpoint = endpoint
	}

	if timeoutStr := os.Getenv("PROMETHEUS_TIMEOUT"); timeoutStr != "" {
		if timeout, err := time.ParseDuration(timeoutStr); err != nil {
			return nil, fmt.Errorf("invalid PROMETHEUS_TIMEOUT: %w", err)
		} else {
			config.PrometheusTimeout = timeout
		}
	}

	if namespace := os.Getenv("KUBE_NAMESPACE"); namespace != "" {
		config.KubeNamespace = namespace
	}

	if selector := os.Getenv("KUBE_LABEL_SELECTOR"); selector != "" {
		config.KubeLabelSelector = selector
	}

	if thresholdStr := os.Getenv("CPU_VARIANCE_THRESHOLD"); thresholdStr != "" {
		if threshold, err := strconv.ParseFloat(thresholdStr, 64); err != nil {
			return nil, fmt.Errorf("invalid CPU_VARIANCE_THRESHOLD: %w", err)
		} else {
			config.CPUVarianceThreshold = threshold
		}
	}

	if thresholdStr := os.Getenv("LAG_VARIANCE_THRESHOLD"); thresholdStr != "" {
		if threshold, err := strconv.ParseFloat(thresholdStr, 64); err != nil {
			return nil, fmt.Errorf("invalid LAG_VARIANCE_THRESHOLD: %w", err)
		} else {
			config.LagVarianceThreshold = threshold
		}
	}

	if minPodsStr := os.Getenv("MIN_PODS_REQUIRED"); minPodsStr != "" {
		if minPods, err := strconv.Atoi(minPodsStr); err != nil {
			return nil, fmt.Errorf("invalid MIN_PODS_REQUIRED: %w", err)
		} else {
			config.MinPodsRequired = minPods
		}
	}

	if dryRunStr := os.Getenv("DRY_RUN"); dryRunStr != "" {
		if dryRun, err := strconv.ParseBool(dryRunStr); err != nil {
			return nil, fmt.Errorf("invalid DRY_RUN: %w", err)
		} else {
			config.DryRun = dryRun
		}
	}

	if logLevel := os.Getenv("LOG_LEVEL"); logLevel != "" {
		config.LogLevel = logLevel
	}

	// Validate the configuration
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

	if c.CPUVarianceThreshold < 0 || c.CPUVarianceThreshold > 1 {
		return fmt.Errorf("CPU_VARIANCE_THRESHOLD must be between 0 and 1")
	}

	if c.LagVarianceThreshold < 0 || c.LagVarianceThreshold > 1 {
		return fmt.Errorf("LAG_VARIANCE_THRESHOLD must be between 0 and 1")
	}

	if c.MinPodsRequired < 1 {
		return fmt.Errorf("MIN_PODS_REQUIRED must be at least 1")
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
