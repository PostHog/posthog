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

	// Decision making thresholds
	CPUVarianceThreshold float64
	LagVarianceThreshold float64
	MinPodsRequired      int

	// Safety and debugging
	DryRun   bool
	LogLevel string
}

// LoadFromEnv loads configuration from environment variables with defaults using Viper
func LoadFromEnv() (*Config, error) {
	v := viper.New()

	// Set defaults
	v.SetDefault("PROMETHEUS_ENDPOINT", "http://localhost:9090")
	v.SetDefault("PROMETHEUS_TIMEOUT", "30s")
	v.SetDefault("KUBE_NAMESPACE", "default")
	v.SetDefault("KUBE_LABEL_SELECTOR", "app=consumer")
	v.SetDefault("CPU_VARIANCE_THRESHOLD", 0.3)
	v.SetDefault("LAG_VARIANCE_THRESHOLD", 0.5)
	v.SetDefault("MIN_PODS_REQUIRED", 3)
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

	config := &Config{
		PrometheusEndpoint:   v.GetString("PROMETHEUS_ENDPOINT"),
		PrometheusTimeout:    timeout,
		KubeNamespace:        v.GetString("KUBE_NAMESPACE"),
		KubeLabelSelector:    v.GetString("KUBE_LABEL_SELECTOR"),
		CPUVarianceThreshold: v.GetFloat64("CPU_VARIANCE_THRESHOLD"),
		LagVarianceThreshold: v.GetFloat64("LAG_VARIANCE_THRESHOLD"),
		MinPodsRequired:      v.GetInt("MIN_PODS_REQUIRED"),
		DryRun:               v.GetBool("DRY_RUN"),
		LogLevel:             v.GetString("LOG_LEVEL"),
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
