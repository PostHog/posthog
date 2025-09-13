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
			"CPU_VARIANCE_THRESHOLD", "MIN_PODS_REQUIRED", "DRY_RUN", "LOG_LEVEL",
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
				os.Setenv("CPU_VARIANCE_THRESHOLD", "0.4")
				os.Setenv("MIN_PODS_REQUIRED", "5")
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
				func(envVar, invalidValue string, checkResult func(*Config)) {
					os.Setenv(envVar, invalidValue)
					config, err := LoadFromEnv()
					if checkResult != nil {
						Expect(err).NotTo(HaveOccurred())
						checkResult(config)
					}
				},
				Entry("invalid CPU threshold becomes zero", "CPU_VARIANCE_THRESHOLD", "invalid", 
					func(c *Config) { Expect(c.CPUVarianceThreshold).To(Equal(0.0)) }),
				Entry("invalid dry run becomes false", "DRY_RUN", "invalid", 
					func(c *Config) { Expect(c.DryRun).To(BeFalse()) }),
			)

			Context("when MIN_PODS_REQUIRED is invalid", func() {
				BeforeEach(func() {
					os.Setenv("MIN_PODS_REQUIRED", "invalid")
				})

				It("should fail validation because zero is invalid for min pods", func() {
					_, err := LoadFromEnv()
					Expect(err).To(HaveOccurred())
					Expect(err.Error()).To(ContainSubstring("MIN_PODS_REQUIRED must be at least 1"))
				})
			})
		})
	})

	Describe("Config validation", func() {
		Context("with valid configuration", func() {
			It("should pass validation", func() {
				config := &Config{
					PrometheusEndpoint:   "http://localhost:9090",
					PrometheusTimeout:    30 * time.Second,
					KubeNamespace:        "default",
					KubeLabelSelector:    "app=consumer",
					DeploymentName:       "ingestion-consumer",
					MetricsTimeWindow:    5 * time.Minute,
					CPUVarianceThreshold: 0.3,
					MinPodsRequired:      3,
					DryRun:               false,
					LogLevel:             "info",
				}

				err := config.Validate()
				Expect(err).NotTo(HaveOccurred())
			})
		})

		Context("with invalid configuration", func() {
			DescribeTable("should fail validation",
				func(modifyConfig func(*Config), expectedError string) {
					config := &Config{
						PrometheusEndpoint:   "http://localhost:9090",
						PrometheusTimeout:    30 * time.Second,
						KubeNamespace:        "default",
						KubeLabelSelector:    "app=consumer", 
						DeploymentName:       "ingestion-consumer",
						MetricsTimeWindow:    5 * time.Minute,
						CPUVarianceThreshold: 0.3,
						MinPodsRequired:      3,
						DryRun:               false,
						LogLevel:             "info",
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
				Entry("CPU threshold too high", func(c *Config) { c.CPUVarianceThreshold = 1.5 }, "CPU_VARIANCE_THRESHOLD must be between 0 and 1"),
				Entry("min pods too low", func(c *Config) { c.MinPodsRequired = 0 }, "MIN_PODS_REQUIRED must be at least 1"),
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
							PrometheusEndpoint:   "http://localhost:9090",
							PrometheusTimeout:    30 * time.Second,
							KubeNamespace:        "default",
							KubeLabelSelector:    "app=consumer",
							DeploymentName:       "ingestion-consumer",
							MetricsTimeWindow:    window,
							CPUVarianceThreshold: 0.3,
							MinPodsRequired:      3,
							DryRun:               false,
							LogLevel:             "info",
						}

						err := config.Validate()
						Expect(err).NotTo(HaveOccurred(), "Should accept %v time window", window)
					}
				})
			})
		})
	})
})