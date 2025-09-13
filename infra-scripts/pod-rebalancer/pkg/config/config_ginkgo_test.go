package config

import (
	"os"
	"time"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
)

// Example of Ginkgo BDD-style testing (similar to Jest)
var _ = Describe("Config with Ginkgo", func() {
	var originalEnv map[string]string

	BeforeEach(func() {
		// Capture and clear environment
		originalEnv = make(map[string]string)
		envVars := []string{
			"PROMETHEUS_ENDPOINT", "PROMETHEUS_TIMEOUT", "KUBE_NAMESPACE",
			"KUBE_LABEL_SELECTOR", "CPU_VARIANCE_THRESHOLD", "LAG_VARIANCE_THRESHOLD",
			"MIN_PODS_REQUIRED", "DRY_RUN", "LOG_LEVEL",
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
			It("should return default configuration", func() {
				config, err := LoadFromEnv()
				
				Expect(err).NotTo(HaveOccurred())
				Expect(config).NotTo(BeNil())
				Expect(config.PrometheusEndpoint).To(Equal("http://localhost:9090"))
				Expect(config.PrometheusTimeout).To(Equal(30 * time.Second))
				Expect(config.KubeNamespace).To(Equal("default"))
				Expect(config.KubeLabelSelector).To(Equal("app=consumer"))
				Expect(config.CPUVarianceThreshold).To(Equal(0.3))
				Expect(config.LagVarianceThreshold).To(Equal(0.5))
				Expect(config.MinPodsRequired).To(Equal(3))
				Expect(config.DryRun).To(BeFalse())
				Expect(config.LogLevel).To(Equal("info"))
			})
		})

		Context("when custom environment variables are set", func() {
			BeforeEach(func() {
				os.Setenv("PROMETHEUS_ENDPOINT", "http://victoriametrics:8428")
				os.Setenv("PROMETHEUS_TIMEOUT", "45s")
				os.Setenv("KUBE_NAMESPACE", "production")
				os.Setenv("KUBE_LABEL_SELECTOR", "app=kafka-consumer,env=prod")
				os.Setenv("CPU_VARIANCE_THRESHOLD", "0.4")
				os.Setenv("LAG_VARIANCE_THRESHOLD", "0.6")
				os.Setenv("MIN_PODS_REQUIRED", "5")
				os.Setenv("DRY_RUN", "true")
				os.Setenv("LOG_LEVEL", "debug")
			})

			It("should load custom configuration values", func() {
				config, err := LoadFromEnv()
				
				Expect(err).NotTo(HaveOccurred())
				Expect(config.PrometheusEndpoint).To(Equal("http://victoriametrics:8428"))
				Expect(config.PrometheusTimeout).To(Equal(45 * time.Second))
				Expect(config.KubeNamespace).To(Equal("production"))
				Expect(config.KubeLabelSelector).To(Equal("app=kafka-consumer,env=prod"))
				Expect(config.CPUVarianceThreshold).To(Equal(0.4))
				Expect(config.LagVarianceThreshold).To(Equal(0.6))
				Expect(config.MinPodsRequired).To(Equal(5))
				Expect(config.DryRun).To(BeTrue())
				Expect(config.LogLevel).To(Equal("debug"))
			})
		})

		Context("when invalid environment variables are provided", func() {
			DescribeTable("should return validation errors",
				func(envVar, value, expectedError string) {
					os.Setenv(envVar, value)
					_, err := LoadFromEnv()
					Expect(err).To(HaveOccurred())
					Expect(err.Error()).To(ContainSubstring(expectedError))
				},
				Entry("invalid timeout format", "PROMETHEUS_TIMEOUT", "invalid", "invalid PROMETHEUS_TIMEOUT"),
				Entry("invalid CPU threshold", "CPU_VARIANCE_THRESHOLD", "invalid", "invalid CPU_VARIANCE_THRESHOLD"),
				Entry("invalid LAG threshold", "LAG_VARIANCE_THRESHOLD", "invalid", "invalid LAG_VARIANCE_THRESHOLD"),
				Entry("invalid min pods", "MIN_PODS_REQUIRED", "invalid", "invalid MIN_PODS_REQUIRED"),
				Entry("invalid dry run", "DRY_RUN", "invalid", "invalid DRY_RUN"),
			)
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
					CPUVarianceThreshold: 0.3,
					LagVarianceThreshold: 0.5,
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
						CPUVarianceThreshold: 0.3,
						LagVarianceThreshold: 0.5,
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
				Entry("CPU threshold too high", func(c *Config) { c.CPUVarianceThreshold = 1.5 }, "CPU_VARIANCE_THRESHOLD must be between 0 and 1"),
				Entry("LAG threshold negative", func(c *Config) { c.LagVarianceThreshold = -0.1 }, "LAG_VARIANCE_THRESHOLD must be between 0 and 1"),
				Entry("min pods too low", func(c *Config) { c.MinPodsRequired = 0 }, "MIN_PODS_REQUIRED must be at least 1"),
				Entry("invalid log level", func(c *Config) { c.LogLevel = "invalid" }, "LOG_LEVEL must be one of: debug, info, warn, error"),
			)
		})
	})
})