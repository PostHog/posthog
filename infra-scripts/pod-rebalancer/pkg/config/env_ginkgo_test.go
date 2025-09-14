package config

import (
	"os"
	"time"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
)

var _ = Describe("Configuration", func() {
	var originalEnv map[string]string

	BeforeEach(func() {
		// Capture and clear environment
		originalEnv = make(map[string]string)
		envVars := []string{
			"PROMETHEUS_ENDPOINT", "PROMETHEUS_TIMEOUT", "KUBE_NAMESPACE",
			"KUBE_LABEL_SELECTOR", "DEPLOYMENT_NAME", "METRICS_TIME_WINDOW",
			"REBALANCE_TOP_K_PODS", "TOLERANCE_MULTIPLIER", "MINIMUM_IMPROVEMENT_PERCENT",
			"HPA_PREFIX", "DRY_RUN", "LOG_LEVEL",
		}
		
		for _, envVar := range envVars {
			originalEnv[envVar] = os.Getenv(envVar)
			os.Unsetenv(envVar)
		}
	})

	AfterEach(func() {
		// Restore original environment
		for key, value := range originalEnv {
			if value != "" {
				os.Setenv(key, value)
			} else {
				os.Unsetenv(key)
			}
		}
	})

	Describe("LoadFromEnv", func() {
		Context("when no environment variables are set", func() {
			It("should return default configuration but fail validation due to missing deployment name", func() {
				config, err := LoadFromEnv()
				
				Expect(err).To(HaveOccurred())
				Expect(err.Error()).To(ContainSubstring("DEPLOYMENT_NAME is required"))
				Expect(config).To(BeNil())
			})
		})

		Context("when all required environment variables are set", func() {
			BeforeEach(func() {
				os.Setenv("DEPLOYMENT_NAME", "ingestion-consumer")
			})

			It("should successfully load configuration", func() {
				config, err := LoadFromEnv()
				
				Expect(err).NotTo(HaveOccurred())
				Expect(config).NotTo(BeNil())
				
				// Test that the config passes validation (tests the interface behavior)
				err = config.Validate()
				Expect(err).NotTo(HaveOccurred())
			})
		})

		Context("when custom environment variables are set", func() {
			BeforeEach(func() {
				os.Setenv("PROMETHEUS_ENDPOINT", "http://victoriametrics:8428")
				os.Setenv("PROMETHEUS_TIMEOUT", "45s")
				os.Setenv("KUBE_NAMESPACE", "production")
				os.Setenv("KUBE_LABEL_SELECTOR", "app=kafka-consumer,env=prod")
				os.Setenv("DEPLOYMENT_NAME", "ingestion-events")
				os.Setenv("METRICS_TIME_WINDOW", "2m")
				os.Setenv("REBALANCE_TOP_K_PODS", "3")
				os.Setenv("TOLERANCE_MULTIPLIER", "2.0")
				os.Setenv("MINIMUM_IMPROVEMENT_PERCENT", "15")
				os.Setenv("HPA_PREFIX", "custom-hpa-")
				os.Setenv("DRY_RUN", "true")
				os.Setenv("LOG_LEVEL", "debug")
			})

			It("should successfully load custom configuration", func() {
				config, err := LoadFromEnv()
				
				Expect(err).NotTo(HaveOccurred())
				Expect(config).NotTo(BeNil())
				
				// Test that the config passes validation (tests the interface behavior)
				err = config.Validate()
				Expect(err).NotTo(HaveOccurred())
			})
		})

		Context("when invalid environment variables are provided", func() {
			BeforeEach(func() {
				os.Setenv("DEPLOYMENT_NAME", "ingestion-consumer") // Required for validation
			})

			DescribeTable("should return validation errors",
				func(envVar, value, expectedError string) {
					os.Setenv(envVar, value)
					_, err := LoadFromEnv()
					Expect(err).To(HaveOccurred())
					Expect(err.Error()).To(ContainSubstring(expectedError))
				},
				Entry("invalid timeout format", "PROMETHEUS_TIMEOUT", "invalid", "invalid PROMETHEUS_TIMEOUT"),
				Entry("invalid metrics time window", "METRICS_TIME_WINDOW", "invalid", "invalid METRICS_TIME_WINDOW"),
			)
		})

		Context("with Viper's type conversion behavior", func() {
			BeforeEach(func() {
				os.Setenv("DEPLOYMENT_NAME", "ingestion-consumer") // Required for validation
			})

			DescribeTable("should handle invalid values by using zero values or defaults",
				func(envVar, invalidValue string, checkResult func(*Config), expectError bool) {
					os.Setenv(envVar, invalidValue)
					config, err := LoadFromEnv()
					if expectError {
						Expect(err).To(HaveOccurred())
					} else if checkResult != nil {
						Expect(err).NotTo(HaveOccurred())
						checkResult(config)
					}
				},
				Entry("invalid rebalance top k becomes zero and fails validation", "REBALANCE_TOP_K_PODS", "invalid", 
					nil, true),
				Entry("invalid tolerance multiplier becomes zero and fails validation", "TOLERANCE_MULTIPLIER", "invalid", 
					nil, true),
				Entry("invalid dry run becomes false", "DRY_RUN", "invalid", 
					func(c *Config) { Expect(c.DryRun).To(BeFalse()) }, false),
			)


			Context("when REBALANCE_TOP_K_PODS is invalid", func() {
				BeforeEach(func() {
					os.Setenv("REBALANCE_TOP_K_PODS", "invalid")
				})

				It("should fail validation because zero is invalid for top k pods", func() {
					_, err := LoadFromEnv()
					Expect(err).To(HaveOccurred())
					Expect(err.Error()).To(ContainSubstring("REBALANCE_TOP_K_PODS must be at least 1"))
				})
			})
		})
	})

	Describe("Config validation", func() {
		Context("with valid configuration", func() {
			It("should pass validation", func() {
				config := &Config{
					PrometheusEndpoint:        "http://localhost:9090",
					PrometheusTimeout:         30 * time.Second,
					KubeNamespace:             "default",
					KubeLabelSelector:         "app=consumer",
					DeploymentName:            "ingestion-consumer",
					MetricsTimeWindow:         5 * time.Minute,
					RebalanceTopKPods:         2,
					ToleranceMultiplier:       1.5,
					MinimumImprovementPercent: 10.0,
					HPAPrefix:                 "keda-hpa-",
					MinimumPodsRequired:       2,
					DryRun:                    false,
					LogLevel:                  "info",
				}

				err := config.Validate()
				Expect(err).NotTo(HaveOccurred())
			})
		})

		Context("with invalid configuration", func() {
			DescribeTable("should fail validation",
				func(modifyConfig func(*Config), expectedError string) {
					config := &Config{
						PrometheusEndpoint:        "http://localhost:9090",
						PrometheusTimeout:         30 * time.Second,
						KubeNamespace:             "default",
						KubeLabelSelector:         "app=consumer", 
						DeploymentName:            "ingestion-consumer",
						MetricsTimeWindow:         5 * time.Minute,
						RebalanceTopKPods:         2,
						ToleranceMultiplier:       1.5,
						MinimumImprovementPercent: 10.0,
						HPAPrefix:                 "keda-hpa-",
						MinimumPodsRequired:       2,
						DryRun:                    false,
						LogLevel:                  "info",
					}
					
					modifyConfig(config)
					
					err := config.Validate()
					Expect(err).To(HaveOccurred())
					Expect(err.Error()).To(ContainSubstring(expectedError))
				},
				Entry("empty endpoint", func(c *Config) { c.PrometheusEndpoint = "" }, "PROMETHEUS_ENDPOINT is required"),
				Entry("negative timeout", func(c *Config) { c.PrometheusTimeout = -1 * time.Second }, "PROMETHEUS_TIMEOUT must be positive"),
				Entry("empty namespace", func(c *Config) { c.KubeNamespace = "" }, "KUBE_NAMESPACE is required"),
				Entry("empty label selector", func(c *Config) { c.KubeLabelSelector = "" }, "KUBE_LABEL_SELECTOR is required"),
				Entry("empty deployment name", func(c *Config) { c.DeploymentName = "" }, "DEPLOYMENT_NAME is required"),
				Entry("rebalance top k too low", func(c *Config) { c.RebalanceTopKPods = 0 }, "REBALANCE_TOP_K_PODS must be at least 1"),
				Entry("tolerance multiplier too low", func(c *Config) { c.ToleranceMultiplier = 0.5 }, "TOLERANCE_MULTIPLIER must be at least 1.0"),
				Entry("improvement percent negative", func(c *Config) { c.MinimumImprovementPercent = -5 }, "MINIMUM_IMPROVEMENT_PERCENT must be between 0 and 100"),
				Entry("improvement percent too high", func(c *Config) { c.MinimumImprovementPercent = 150 }, "MINIMUM_IMPROVEMENT_PERCENT must be between 0 and 100"),
				Entry("minimum pods too low", func(c *Config) { c.MinimumPodsRequired = 0 }, "MINIMUM_PODS_REQUIRED must be at least 1"),
				Entry("invalid log level", func(c *Config) { c.LogLevel = "invalid" }, "LOG_LEVEL must be one of: debug, info, warn, error"),
			)
		})

		Describe("time window validation", func() {
			Context("with different time window values", func() {
				It("should accept various valid time durations", func() {
					validWindows := []time.Duration{
						30 * time.Second,
						time.Minute,
						5 * time.Minute,
						10 * time.Minute,
					}

					for _, window := range validWindows {
						config := &Config{
							PrometheusEndpoint:        "http://localhost:9090",
							PrometheusTimeout:         30 * time.Second,
							KubeNamespace:             "default",
							KubeLabelSelector:         "app=consumer",
							DeploymentName:            "ingestion-consumer",
							MetricsTimeWindow:         window,
							RebalanceTopKPods:         2,
							ToleranceMultiplier:       1.5,
							MinimumImprovementPercent: 10.0,
							HPAPrefix:                 "keda-hpa-",
							MinimumPodsRequired:       2,
							DryRun:                    false,
							LogLevel:                  "info",
						}

						err := config.Validate()
						Expect(err).NotTo(HaveOccurred(), "Should accept %v time window", window)
					}
				})
			})
		})
	})
})