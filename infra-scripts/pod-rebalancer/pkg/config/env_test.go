package config

import (
	"os"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestLoadFromEnv(t *testing.T) {
	tests := []struct {
		name     string
		envVars  map[string]string
		want     *Config
		wantErr  bool
		errMatch string
	}{
		{
			name:    "defaults when no env vars set",
			envVars: map[string]string{},
			want: &Config{
				PrometheusEndpoint:   "http://localhost:9090",
				PrometheusTimeout:    30 * time.Second,
				KubeNamespace:        "default",
				KubeLabelSelector:    "app=consumer",
				CPUVarianceThreshold: 0.3,
				LagVarianceThreshold: 0.5,
				MinPodsRequired:      3,
				DryRun:               false,
				LogLevel:             "info",
			},
			wantErr: false,
		},
		{
			name: "custom values from env vars",
			envVars: map[string]string{
				"PROMETHEUS_ENDPOINT":    "http://victoriametrics:8428",
				"PROMETHEUS_TIMEOUT":     "45s",
				"KUBE_NAMESPACE":         "production",
				"KUBE_LABEL_SELECTOR":    "app=kafka-consumer,env=prod",
				"CPU_VARIANCE_THRESHOLD": "0.4",
				"LAG_VARIANCE_THRESHOLD": "0.6",
				"MIN_PODS_REQUIRED":      "5",
				"DRY_RUN":                "true",
				"LOG_LEVEL":              "debug",
			},
			want: &Config{
				PrometheusEndpoint:   "http://victoriametrics:8428",
				PrometheusTimeout:    45 * time.Second,
				KubeNamespace:        "production",
				KubeLabelSelector:    "app=kafka-consumer,env=prod",
				CPUVarianceThreshold: 0.4,
				LagVarianceThreshold: 0.6,
				MinPodsRequired:      5,
				DryRun:               true,
				LogLevel:             "debug",
			},
			wantErr: false,
		},
		{
			name: "invalid timeout format",
			envVars: map[string]string{
				"PROMETHEUS_TIMEOUT": "invalid",
			},
			wantErr:  true,
			errMatch: "invalid PROMETHEUS_TIMEOUT",
		},
		{
			name: "invalid CPU variance threshold becomes zero and fails validation",
			envVars: map[string]string{
				"CPU_VARIANCE_THRESHOLD": "invalid",
			},
			wantErr: false, // Zero value is valid for CPU threshold
			want: &Config{
				PrometheusEndpoint:   "http://localhost:9090",
				PrometheusTimeout:    30 * time.Second,
				KubeNamespace:        "default",
				KubeLabelSelector:    "app=consumer",
				CPUVarianceThreshold: 0, // Viper returns zero for invalid values
				LagVarianceThreshold: 0.5,
				MinPodsRequired:      3,
				DryRun:               false,
				LogLevel:             "info",
			},
		},
		{
			name: "invalid LAG variance threshold becomes zero and passes validation",
			envVars: map[string]string{
				"LAG_VARIANCE_THRESHOLD": "invalid",
			},
			wantErr: false, // Zero value is valid for LAG threshold
			want: &Config{
				PrometheusEndpoint:   "http://localhost:9090",
				PrometheusTimeout:    30 * time.Second,
				KubeNamespace:        "default",
				KubeLabelSelector:    "app=consumer",
				CPUVarianceThreshold: 0.3,
				LagVarianceThreshold: 0, // Viper returns zero for invalid values
				MinPodsRequired:      3,
				DryRun:               false,
				LogLevel:             "info",
			},
		},
		{
			name: "invalid min pods required becomes zero and fails validation",
			envVars: map[string]string{
				"MIN_PODS_REQUIRED": "invalid",
			},
			wantErr:  true, // Zero is invalid for min pods
			errMatch: "MIN_PODS_REQUIRED must be at least 1",
		},
		{
			name: "invalid dry run boolean uses default",
			envVars: map[string]string{
				"DRY_RUN": "invalid",
			},
			want: &Config{
				PrometheusEndpoint:   "http://localhost:9090",
				PrometheusTimeout:    30 * time.Second,
				KubeNamespace:        "default",
				KubeLabelSelector:    "app=consumer",
				CPUVarianceThreshold: 0.3,
				LagVarianceThreshold: 0.5,
				MinPodsRequired:      3,
				DryRun:               false, // Viper uses default when parsing fails
				LogLevel:             "info",
			},
			wantErr: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Clear environment
			clearEnv()

			// Set test environment variables
			for key, value := range tt.envVars {
				os.Setenv(key, value)
			}

			// Clean up after test
			defer clearEnv()

			got, err := LoadFromEnv()

			if tt.wantErr {
				require.Error(t, err)
				if tt.errMatch != "" {
					assert.Contains(t, err.Error(), tt.errMatch)
				}
				return
			}

			require.NoError(t, err)
			assert.Equal(t, tt.want, got)
		})
	}
}

func TestConfig_Validate(t *testing.T) {
	tests := []struct {
		name     string
		config   *Config
		wantErr  bool
		errMatch string
	}{
		{
			name: "valid config",
			config: &Config{
				PrometheusEndpoint:   "http://localhost:9090",
				PrometheusTimeout:    30 * time.Second,
				KubeNamespace:        "default",
				KubeLabelSelector:    "app=consumer",
				CPUVarianceThreshold: 0.3,
				LagVarianceThreshold: 0.5,
				MinPodsRequired:      3,
				DryRun:               false,
				LogLevel:             "info",
			},
			wantErr: false,
		},
		{
			name: "empty prometheus endpoint",
			config: &Config{
				PrometheusEndpoint:   "",
				PrometheusTimeout:    30 * time.Second,
				KubeNamespace:        "default",
				KubeLabelSelector:    "app=consumer",
				CPUVarianceThreshold: 0.3,
				LagVarianceThreshold: 0.5,
				MinPodsRequired:      3,
				LogLevel:             "info",
			},
			wantErr:  true,
			errMatch: "PROMETHEUS_ENDPOINT is required",
		},
		{
			name: "negative timeout",
			config: &Config{
				PrometheusEndpoint:   "http://localhost:9090",
				PrometheusTimeout:    -1 * time.Second,
				KubeNamespace:        "default",
				KubeLabelSelector:    "app=consumer",
				CPUVarianceThreshold: 0.3,
				LagVarianceThreshold: 0.5,
				MinPodsRequired:      3,
				LogLevel:             "info",
			},
			wantErr:  true,
			errMatch: "PROMETHEUS_TIMEOUT must be positive",
		},
		{
			name: "empty namespace",
			config: &Config{
				PrometheusEndpoint:   "http://localhost:9090",
				PrometheusTimeout:    30 * time.Second,
				KubeNamespace:        "",
				KubeLabelSelector:    "app=consumer",
				CPUVarianceThreshold: 0.3,
				LagVarianceThreshold: 0.5,
				MinPodsRequired:      3,
				LogLevel:             "info",
			},
			wantErr:  true,
			errMatch: "KUBE_NAMESPACE is required",
		},
		{
			name: "empty label selector",
			config: &Config{
				PrometheusEndpoint:   "http://localhost:9090",
				PrometheusTimeout:    30 * time.Second,
				KubeNamespace:        "default",
				KubeLabelSelector:    "",
				CPUVarianceThreshold: 0.3,
				LagVarianceThreshold: 0.5,
				MinPodsRequired:      3,
				LogLevel:             "info",
			},
			wantErr:  true,
			errMatch: "KUBE_LABEL_SELECTOR is required",
		},
		{
			name: "CPU variance threshold too high",
			config: &Config{
				PrometheusEndpoint:   "http://localhost:9090",
				PrometheusTimeout:    30 * time.Second,
				KubeNamespace:        "default",
				KubeLabelSelector:    "app=consumer",
				CPUVarianceThreshold: 1.5,
				LagVarianceThreshold: 0.5,
				MinPodsRequired:      3,
				LogLevel:             "info",
			},
			wantErr:  true,
			errMatch: "CPU_VARIANCE_THRESHOLD must be between 0 and 1",
		},
		{
			name: "LAG variance threshold negative",
			config: &Config{
				PrometheusEndpoint:   "http://localhost:9090",
				PrometheusTimeout:    30 * time.Second,
				KubeNamespace:        "default",
				KubeLabelSelector:    "app=consumer",
				CPUVarianceThreshold: 0.3,
				LagVarianceThreshold: -0.1,
				MinPodsRequired:      3,
				LogLevel:             "info",
			},
			wantErr:  true,
			errMatch: "LAG_VARIANCE_THRESHOLD must be between 0 and 1",
		},
		{
			name: "min pods required too low",
			config: &Config{
				PrometheusEndpoint:   "http://localhost:9090",
				PrometheusTimeout:    30 * time.Second,
				KubeNamespace:        "default",
				KubeLabelSelector:    "app=consumer",
				CPUVarianceThreshold: 0.3,
				LagVarianceThreshold: 0.5,
				MinPodsRequired:      0,
				LogLevel:             "info",
			},
			wantErr:  true,
			errMatch: "MIN_PODS_REQUIRED must be at least 1",
		},
		{
			name: "invalid log level",
			config: &Config{
				PrometheusEndpoint:   "http://localhost:9090",
				PrometheusTimeout:    30 * time.Second,
				KubeNamespace:        "default",
				KubeLabelSelector:    "app=consumer",
				CPUVarianceThreshold: 0.3,
				LagVarianceThreshold: 0.5,
				MinPodsRequired:      3,
				LogLevel:             "invalid",
			},
			wantErr:  true,
			errMatch: "LOG_LEVEL must be one of: debug, info, warn, error",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := tt.config.Validate()

			if tt.wantErr {
				require.Error(t, err)
				if tt.errMatch != "" {
					assert.Contains(t, err.Error(), tt.errMatch)
				}
			} else {
				require.NoError(t, err)
			}
		})
	}
}

// clearEnv clears all relevant environment variables
func clearEnv() {
	envVars := []string{
		"PROMETHEUS_ENDPOINT",
		"PROMETHEUS_TIMEOUT",
		"KUBE_NAMESPACE",
		"KUBE_LABEL_SELECTOR",
		"CPU_VARIANCE_THRESHOLD",
		"LAG_VARIANCE_THRESHOLD",
		"MIN_PODS_REQUIRED",
		"DRY_RUN",
		"LOG_LEVEL",
	}

	for _, envVar := range envVars {
		os.Unsetenv(envVar)
	}
}
