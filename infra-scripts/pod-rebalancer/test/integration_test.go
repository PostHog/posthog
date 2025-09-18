package test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"time"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
	v1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes/fake"

	"github.com/posthog/pod-rebalancer/pkg/config"
	"github.com/posthog/pod-rebalancer/pkg/kubernetes"
	"github.com/posthog/pod-rebalancer/pkg/logging"
	"github.com/posthog/pod-rebalancer/pkg/metrics"
	"github.com/posthog/pod-rebalancer/pkg/prometheus"
)

var _ = Describe("Simple Integration Tests", func() {
	var (
		ctx            context.Context
		logger         *logging.Logger
		mockPrometheus *httptest.Server
		k8sClient      *fake.Clientset
		namespace      string
		deploymentName string
	)

	BeforeEach(func() {
		ctx = context.Background()
		logger, _ = logging.New("error") // Use error level to minimize test output
		namespace = "test-namespace"
		deploymentName = "test-deployment"
		k8sClient = fake.NewSimpleClientset()

		// Set up environment variables
		os.Setenv("PROMETHEUS_ENDPOINT", "http://localhost:9090")
		os.Setenv("PROMETHEUS_TIMEOUT", "30s")
		os.Setenv("KUBE_NAMESPACE", namespace)
		os.Setenv("KUBE_LABEL_SELECTOR", "app=test")
		os.Setenv("DEPLOYMENT_NAME", deploymentName)
		os.Setenv("METRICS_TIME_WINDOW", "5m")
		os.Setenv("REBALANCE_TOP_K_PODS", "2")
		os.Setenv("TOLERANCE_MULTIPLIER", "1.5")
		os.Setenv("MINIMUM_IMPROVEMENT_PERCENT", "10.0")
		os.Setenv("MINIMUM_PODS_REQUIRED", "2")
		os.Setenv("HPA_PREFIX", "keda-hpa-")
		os.Setenv("DRY_RUN", "true")
		os.Setenv("LOG_LEVEL", "info")
	})

	AfterEach(func() {
		if mockPrometheus != nil {
			mockPrometheus.Close()
		}
		// Clean up environment variables
		envVars := []string{
			"PROMETHEUS_ENDPOINT", "PROMETHEUS_TIMEOUT", "KUBE_NAMESPACE",
			"KUBE_LABEL_SELECTOR", "DEPLOYMENT_NAME", "METRICS_TIME_WINDOW",
			"REBALANCE_TOP_K_PODS", "TOLERANCE_MULTIPLIER", "MINIMUM_IMPROVEMENT_PERCENT",
			"MINIMUM_PODS_REQUIRED", "HPA_PREFIX", "DRY_RUN", "LOG_LEVEL",
		}
		for _, env := range envVars {
			os.Unsetenv(env)
		}
	})

	Describe("Configuration Integration", func() {
		It("should load configuration from environment variables", func() {
			cfg, err := config.LoadFromEnv()
			Expect(err).NotTo(HaveOccurred())
			Expect(cfg.DeploymentName).To(Equal(deploymentName))
			Expect(cfg.KubeNamespace).To(Equal(namespace))
			Expect(cfg.DryRun).To(BeTrue())
			Expect(cfg.MinimumPodsRequired).To(Equal(2))
			Expect(cfg.ToleranceMultiplier).To(Equal(1.5))
		})

		It("should fail validation with missing required fields", func() {
			os.Unsetenv("DEPLOYMENT_NAME")
			_, err := config.LoadFromEnv()
			Expect(err).To(HaveOccurred())
			Expect(err.Error()).To(ContainSubstring("DEPLOYMENT_NAME is required"))
		})
	})

	Describe("Prometheus Client Integration", func() {
		BeforeEach(func() {
			mockPrometheus = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				// Simple successful response for any query
				response := `{"status":"success","data":{"resultType":"vector",` +
					`"result":[{"metric":{},"value":[1640995200,"1.0"]}]}}`
				w.Header().Set("Content-Type", "application/json")
				w.Write([]byte(response))
			}))
		})

		It("should successfully create and query Prometheus client", func() {
			client, err := prometheus.NewClient(mockPrometheus.URL, 30*time.Second, logger)
			Expect(err).NotTo(HaveOccurred())

			result, err := client.Query(ctx, "up")
			Expect(err).NotTo(HaveOccurred())
			Expect(result).NotTo(BeNil())
		})

		It("should handle connection errors gracefully", func() {
			client, err := prometheus.NewClient("http://unreachable-host:9090", 1*time.Second, logger)
			Expect(err).NotTo(HaveOccurred())

			_, err = client.Query(ctx, "up")
			Expect(err).To(HaveOccurred())
		})
	})

	Describe("CPU Metrics Integration", func() {
		BeforeEach(func() {
			mockPrometheus = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				var query string
				if r.Method == "POST" {
					r.ParseForm()
					query = r.Form.Get("query")
				} else {
					query = r.URL.Query().Get("query")
				}

				switch {
				case strings.Contains(query, "kube_pod_container_resource_limits"):
					response := `{"status":"success","data":{"resultType":"vector",` +
						`"result":[{"metric":{},"value":[1640995200,"2.0"]}]}}`
					w.Header().Set("Content-Type", "application/json")
					w.Write([]byte(response))
				case strings.Contains(query, "kube_pod_container_resource_requests") && !strings.Contains(query, "avg("):
					response := `{"status":"success","data":{"resultType":"vector",` +
						`"result":[{"metric":{},"value":[1640995200,"1.0"]}]}}`
					w.Header().Set("Content-Type", "application/json")
					w.Write([]byte(response))
				case strings.Contains(query, "bottomk"):
					response := `{"status":"success","data":{"resultType":"vector",` +
						`"result":[{"metric":{"pod":"low-cpu-pod-1"},"value":[1640995200,"0.2"]},` +
						`{"metric":{"pod":"low-cpu-pod-2"},"value":[1640995200,"0.3"]}]}}`
					w.Header().Set("Content-Type", "application/json")
					w.Write([]byte(response))
				default:
					// Default response for other queries
					response := `{"status":"success","data":{"resultType":"vector","result":[]}}`
					w.Header().Set("Content-Type", "application/json")
					w.Write([]byte(response))
				}
			}))
		})

		It("should fetch CPU metrics successfully", func() {
			client, err := prometheus.NewClient(mockPrometheus.URL, 30*time.Second, logger)
			Expect(err).NotTo(HaveOccurred())

			cpuMetrics := metrics.NewCPUMetrics(
				client, logger,
				namespace, deploymentName, 5*time.Minute,
			)

			limits, err := cpuMetrics.FetchCPULimits(ctx)
			Expect(err).NotTo(HaveOccurred())
			Expect(limits).To(Equal(2.0))

			requests, err := cpuMetrics.FetchCPURequests(ctx)
			Expect(err).NotTo(HaveOccurred())
			Expect(requests).To(Equal(1.0))

			bottomPods, err := cpuMetrics.FetchBottomKPods(ctx, 2)
			Expect(err).NotTo(HaveOccurred())
			Expect(bottomPods).To(HaveLen(2))
			Expect(bottomPods).To(HaveKeyWithValue("low-cpu-pod-1", 0.2))
			Expect(bottomPods).To(HaveKeyWithValue("low-cpu-pod-2", 0.3))
		})
	})

	Describe("Kubernetes Manager Integration", func() {
		BeforeEach(func() {
			// Create test pods
			testPods := []*v1.Pod{
				{
					ObjectMeta: metav1.ObjectMeta{
						Name:      "test-pod-1",
						Namespace: namespace,
						Labels:    map[string]string{"app": "test"},
					},
					Status: v1.PodStatus{Phase: v1.PodRunning},
				},
				{
					ObjectMeta: metav1.ObjectMeta{
						Name:      "test-pod-2",
						Namespace: namespace,
						Labels:    map[string]string{"app": "test"},
					},
					Status: v1.PodStatus{Phase: v1.PodRunning},
				},
				{
					ObjectMeta: metav1.ObjectMeta{
						Name:      "test-pod-3",
						Namespace: namespace,
						Labels:    map[string]string{"app": "test"},
					},
					Status: v1.PodStatus{Phase: v1.PodRunning},
				},
			}

			for _, pod := range testPods {
				_, err := k8sClient.CoreV1().Pods(namespace).Create(ctx, pod, metav1.CreateOptions{})
				Expect(err).NotTo(HaveOccurred())
			}
		})

		It("should successfully manage pod deletions", func() {
			manager := kubernetes.NewManagerWithClient(k8sClient, namespace, true, logger)

			// Validate minimum pods
			err := manager.ValidateMinimumPods(ctx, []string{"test-pod-1"}, "app=test", 2)
			Expect(err).NotTo(HaveOccurred())

			// Delete pods (dry run)
			result, err := manager.DeletePods(ctx, []string{"test-pod-1"})
			Expect(err).NotTo(HaveOccurred())
			Expect(result.Attempted).To(Equal([]string{"test-pod-1"}))
			Expect(result.Deleted).To(Equal([]string{"test-pod-1"}))
			Expect(result.Errors).To(BeEmpty())
		})

		It("should prevent deletion below minimum threshold", func() {
			manager := kubernetes.NewManagerWithClient(k8sClient, namespace, true, logger)

			// Try to delete too many pods
			err := manager.ValidateMinimumPods(ctx, []string{"test-pod-1", "test-pod-2", "test-pod-3"}, "app=test", 2)
			Expect(err).To(HaveOccurred())
			Expect(err.Error()).To(ContainSubstring("deletion would leave 0 pods, minimum required is 2"))
		})
	})

	Describe("Error Handling", func() {
		It("should handle Prometheus server errors", func() {
			// Mock server that returns errors
			mockPrometheus = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.WriteHeader(http.StatusInternalServerError)
				w.Write([]byte("Internal Server Error"))
			}))

			client, err := prometheus.NewClient(mockPrometheus.URL, 30*time.Second, logger)
			Expect(err).NotTo(HaveOccurred())

			cpuMetrics := metrics.NewCPUMetrics(
				client, logger,
				namespace, deploymentName, 5*time.Minute,
			)

			_, err = cpuMetrics.FetchCPULimits(ctx)
			Expect(err).To(HaveOccurred())
			Expect(err.Error()).To(ContainSubstring("failed to query CPU limits"))
		})

		It("should handle invalid Prometheus responses", func() {
			// Mock server that returns invalid JSON
			mockPrometheus = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.Header().Set("Content-Type", "application/json")
				w.Write([]byte("invalid json"))
			}))

			client, err := prometheus.NewClient(mockPrometheus.URL, 30*time.Second, logger)
			Expect(err).NotTo(HaveOccurred())

			_, err = client.Query(ctx, "up")
			Expect(err).To(HaveOccurred())
		})
	})

	Describe("Performance Tests", func() {
		It("should complete operations within reasonable time", func() {
			mockPrometheus = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				response := `{"status":"success","data":{"resultType":"vector",` +
					`"result":[{"metric":{},"value":[1640995200,"1.0"]}]}}`
				w.Header().Set("Content-Type", "application/json")
				w.Write([]byte(response))
			}))

			start := time.Now()

			client, err := prometheus.NewClient(mockPrometheus.URL, 30*time.Second, logger)
			Expect(err).NotTo(HaveOccurred())

			cpuMetrics := metrics.NewCPUMetrics(
				client, logger,
				namespace, deploymentName, 5*time.Minute,
			)

			// Perform multiple operations
			_, err = cpuMetrics.FetchCPULimits(ctx)
			Expect(err).NotTo(HaveOccurred())

			_, err = cpuMetrics.FetchCPURequests(ctx)
			Expect(err).NotTo(HaveOccurred())

			duration := time.Since(start)
			Expect(duration).To(BeNumerically("<", 5*time.Second))
		})
	})
})
