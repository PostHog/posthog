package metrics

import (
	"context"
	"errors"
	"time"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
	"github.com/prometheus/common/model"
	"github.com/stretchr/testify/mock"
	"go.uber.org/zap"
)

// MockPrometheusClient implements PrometheusClient interface for testing using testify mock
type MockPrometheusClient struct {
	mock.Mock
}

func (m *MockPrometheusClient) Query(ctx context.Context, query string) (model.Value, error) {
	args := m.Called(ctx, query)

	var result model.Value
	if args.Get(0) != nil {
		result = args.Get(0).(model.Value)
	}

	return result, args.Error(1)
}

var _ = Describe("CPUMetricsFetcher", func() {
	var (
		client         *MockPrometheusClient
		logger         *zap.Logger
		namespace      string
		deploymentName string
		timeWindow     time.Duration
		fetcher        *CPUMetricsFetcher
		ctx            context.Context
	)

	BeforeEach(func() {
		client = &MockPrometheusClient{}
		logger = zap.NewNop()
		namespace = "posthog"
		deploymentName = "ingestion-consumer"
		timeWindow = time.Minute
		ctx = context.Background()
	})

	Describe("FetchCPUUsage", func() {
		BeforeEach(func() {
			fetcher = NewCPUMetricsFetcher(client, logger, namespace, deploymentName, timeWindow)
		})

		Context("with successful vector query", func() {
			BeforeEach(func() {
				vectorResult := model.Vector{
					&model.Sample{
						Metric: model.Metric{
							"pod":       "consumer-pod-1",
							"container": "consumer",
						},
						Value: 0.5,
					},
					&model.Sample{
						Metric: model.Metric{
							"pod":       "consumer-pod-2",
							"container": "consumer",
						},
						Value: 0.3,
					},
				}
				expectedQuery := `sum by(pod) (rate(container_cpu_usage_seconds_total{namespace="posthog", container="ingestion-consumer"}[1m0s]))`
				client.On("Query", mock.Anything, expectedQuery).Return(vectorResult, nil)
			})

			It("should return CPU usage for all pods", func() {
				usage, err := fetcher.FetchCPUUsage(ctx)

				Expect(err).NotTo(HaveOccurred())
				Expect(usage).To(HaveLen(2))
				Expect(usage["consumer-pod-1"]).To(Equal(0.5))
				Expect(usage["consumer-pod-2"]).To(Equal(0.3))
				client.AssertExpectations(GinkgoT())
			})
		})

		Context("with successful matrix query", func() {
			BeforeEach(func() {
				matrixResult := model.Matrix{
					&model.SampleStream{
						Metric: model.Metric{
							"pod": "consumer-pod-1",
						},
						Values: []model.SamplePair{
							{Timestamp: 1000, Value: 0.4},
							{Timestamp: 2000, Value: 0.6}, // Latest value
						},
					},
				}
				expectedQuery := `sum by(pod) (rate(container_cpu_usage_seconds_total{namespace="posthog", container="ingestion-consumer"}[1m0s]))`
				client.On("Query", mock.Anything, expectedQuery).Return(matrixResult, nil)
			})

			It("should return the latest value from the matrix", func() {
				usage, err := fetcher.FetchCPUUsage(ctx)

				Expect(err).NotTo(HaveOccurred())
				Expect(usage).To(HaveLen(1))
				Expect(usage["consumer-pod-1"]).To(Equal(0.6))
				client.AssertExpectations(GinkgoT())
			})
		})

		Context("with empty vector result", func() {
			BeforeEach(func() {
				expectedQuery := `sum by(pod) (rate(container_cpu_usage_seconds_total{namespace="posthog", container="ingestion-consumer"}[1m0s]))`
				client.On("Query", mock.Anything, expectedQuery).Return(model.Vector{}, nil)
			})

			It("should return empty usage map", func() {
				usage, err := fetcher.FetchCPUUsage(ctx)

				Expect(err).NotTo(HaveOccurred())
				Expect(usage).To(BeEmpty())
				client.AssertExpectations(GinkgoT())
			})
		})

		Context("with prometheus query error", func() {
			BeforeEach(func() {
				expectedQuery := `sum by(pod) (rate(container_cpu_usage_seconds_total{namespace="posthog", container="ingestion-consumer"}[1m0s]))`
				client.On("Query", mock.Anything, expectedQuery).Return(nil, errors.New("connection failed"))
			})

			It("should return an error", func() {
				usage, err := fetcher.FetchCPUUsage(ctx)

				Expect(err).To(HaveOccurred())
				Expect(err.Error()).To(ContainSubstring("failed to query CPU metrics"))
				Expect(usage).To(BeNil())
				client.AssertExpectations(GinkgoT())
			})
		})

		Context("with vector missing pod labels", func() {
			BeforeEach(func() {
				vectorResult := model.Vector{
					&model.Sample{
						Metric: model.Metric{
							"container": "consumer",
							// Missing "pod" label
						},
						Value: 0.5,
					},
					&model.Sample{
						Metric: model.Metric{
							"pod":       "consumer-pod-1",
							"container": "consumer",
						},
						Value: 0.3,
					},
				}
				expectedQuery := `sum by(pod) (rate(container_cpu_usage_seconds_total{namespace="posthog", container="ingestion-consumer"}[1m0s]))`
				client.On("Query", mock.Anything, expectedQuery).Return(vectorResult, nil)
			})

			It("should only include pods with valid labels", func() {
				usage, err := fetcher.FetchCPUUsage(ctx)

				Expect(err).NotTo(HaveOccurred())
				Expect(usage).To(HaveLen(1))
				Expect(usage["consumer-pod-1"]).To(Equal(0.3))
				client.AssertExpectations(GinkgoT())
			})
		})

		Context("with matrix containing empty values", func() {
			BeforeEach(func() {
				matrixResult := model.Matrix{
					&model.SampleStream{
						Metric: model.Metric{
							"pod": "consumer-pod-1",
						},
						Values: []model.SamplePair{}, // Empty values array
					},
				}
				expectedQuery := `sum by(pod) (rate(container_cpu_usage_seconds_total{namespace="posthog", container="ingestion-consumer"}[1m0s]))`
				client.On("Query", mock.Anything, expectedQuery).Return(matrixResult, nil)
			})

			It("should return empty usage map", func() {
				usage, err := fetcher.FetchCPUUsage(ctx)

				Expect(err).NotTo(HaveOccurred())
				Expect(usage).To(BeEmpty())
				client.AssertExpectations(GinkgoT())
			})
		})

		Context("with unsupported result type", func() {
			BeforeEach(func() {
				scalarResult := &model.Scalar{Value: 1.0, Timestamp: 1000}
				expectedQuery := `sum by(pod) (rate(container_cpu_usage_seconds_total{namespace="posthog", container="ingestion-consumer"}[1m0s]))`
				client.On("Query", mock.Anything, expectedQuery).Return(scalarResult, nil)
			})

			It("should return an error", func() {
				usage, err := fetcher.FetchCPUUsage(ctx)

				Expect(err).To(HaveOccurred())
				Expect(err.Error()).To(ContainSubstring("unexpected result type from CPU query"))
				Expect(usage).To(BeNil())
				client.AssertExpectations(GinkgoT())
			})
		})
	})

	Describe("Query construction", func() {
		DescribeTable("should construct correct queries with different parameters",
			func(ns, deployment string, window time.Duration, expectedQuery string) {
				fetcher = NewCPUMetricsFetcher(client, logger, ns, deployment, window)
				client.On("Query", mock.Anything, expectedQuery).Return(model.Vector{}, nil)

				_, err := fetcher.FetchCPUUsage(ctx)

				Expect(err).NotTo(HaveOccurred())
				client.AssertExpectations(GinkgoT())
			},
			Entry("posthog ingestion consumer with 1m window",
				"posthog", "ingestion-consumer", time.Minute,
				`sum by(pod) (rate(container_cpu_usage_seconds_total{namespace="posthog", container="ingestion-consumer"}[1m0s]))`),
			Entry("different namespace with 5m window",
				"production", "ingestion-events", 5*time.Minute,
				`sum by(pod) (rate(container_cpu_usage_seconds_total{namespace="production", container="ingestion-events"}[5m0s]))`),
			Entry("30s time window",
				"posthog", "ingestion-recordings", 30*time.Second,
				`sum by(pod) (rate(container_cpu_usage_seconds_total{namespace="posthog", container="ingestion-recordings"}[30s]))`),
		)
	})

	Describe("FetchCPULimits", func() {
		BeforeEach(func() {
			fetcher = NewCPUMetricsFetcher(client, logger, namespace, deploymentName, timeWindow)
		})

		Context("with successful vector result", func() {
			BeforeEach(func() {
				vectorResult := model.Vector{
					&model.Sample{
						Metric: model.Metric{},
						Value:  4.0,
					},
				}
				expectedQuery := `median(sum(median by (container) (kube_pod_container_resource_limits{resource="cpu", namespace="posthog", container="ingestion-consumer"})))`
				client.On("Query", mock.Anything, expectedQuery).Return(vectorResult, nil)
			})

			It("should return CPU limits value", func() {
				limits, err := fetcher.FetchCPULimits(ctx)

				Expect(err).NotTo(HaveOccurred())
				Expect(limits).To(Equal(4.0))
				client.AssertExpectations(GinkgoT())
			})
		})

		Context("with empty result", func() {
			BeforeEach(func() {
				expectedQuery := `median(sum(median by (container) (kube_pod_container_resource_limits{resource="cpu", namespace="posthog", container="ingestion-consumer"})))`
				client.On("Query", mock.Anything, expectedQuery).Return(model.Vector{}, nil)
			})

			It("should return zero", func() {
				limits, err := fetcher.FetchCPULimits(ctx)

				Expect(err).NotTo(HaveOccurred())
				Expect(limits).To(Equal(0.0))
				client.AssertExpectations(GinkgoT())
			})
		})
	})

	Describe("FetchCPURequests", func() {
		BeforeEach(func() {
			fetcher = NewCPUMetricsFetcher(client, logger, namespace, deploymentName, timeWindow)
		})

		It("should construct correct query and return requests value", func() {
			vectorResult := model.Vector{
				&model.Sample{
					Metric: model.Metric{},
					Value:  2.0,
				},
			}
			expectedQuery := `median(sum(median by (container) (kube_pod_container_resource_requests{resource="cpu", namespace="posthog", container="ingestion-consumer"})))`
			client.On("Query", mock.Anything, expectedQuery).Return(vectorResult, nil)

			requests, err := fetcher.FetchCPURequests(ctx)

			Expect(err).NotTo(HaveOccurred())
			Expect(requests).To(Equal(2.0))
			client.AssertExpectations(GinkgoT())
		})
	})

})
