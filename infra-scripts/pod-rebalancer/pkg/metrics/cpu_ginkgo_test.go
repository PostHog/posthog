package metrics

import (
	"context"
	"errors"
	"time"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
	"github.com/prometheus/common/model"
	"github.com/stretchr/testify/mock"

	"github.com/posthog/pod-rebalancer/pkg/logging"
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

var _ = Describe("CPUMetrics", func() {
	var (
		client         *MockPrometheusClient
		logger         *logging.Logger
		namespace      string
		deploymentName string
		timeWindow     time.Duration
		fetcher        *CPUMetrics
		ctx            context.Context
	)

	BeforeEach(func() {
		client = &MockPrometheusClient{}
		logger, _ = logging.New("error") // Use error level to minimize test output
		namespace = "posthog"
		deploymentName = "ingestion-consumer"
		timeWindow = time.Minute
		ctx = context.Background()
	})

	Describe("FetchCPULimits", func() {
		BeforeEach(func() {
			fetcher = NewCPUMetrics(client, logger, namespace, deploymentName, timeWindow)
		})

		Context("with successful vector result", func() {
			BeforeEach(func() {
				vectorResult := model.Vector{
					&model.Sample{
						Metric: model.Metric{},
						Value:  4.0,
					},
				}
				expectedQuery := `median(sum(median by (container) ` +
					`(kube_pod_container_resource_limits{resource="cpu", namespace="posthog", container="ingestion-consumer"})))`
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
				expectedQuery := `median(sum(median by (container) ` +
					`(kube_pod_container_resource_limits{resource="cpu", namespace="posthog", container="ingestion-consumer"})))`
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
			fetcher = NewCPUMetrics(client, logger, namespace, deploymentName, timeWindow)
		})

		It("should construct correct query and return requests value", func() {
			vectorResult := model.Vector{
				&model.Sample{
					Metric: model.Metric{},
					Value:  2.0,
				},
			}
			expectedQuery := `median(sum(median by (container) ` +
				`(kube_pod_container_resource_requests{resource="cpu", namespace="posthog", container="ingestion-consumer"})))`
			client.On("Query", mock.Anything, expectedQuery).Return(vectorResult, nil)

			requests, err := fetcher.FetchCPURequests(ctx)

			Expect(err).NotTo(HaveOccurred())
			Expect(requests).To(Equal(2.0))
			client.AssertExpectations(GinkgoT())
		})
	})

	Describe("FetchTopKPodsAboveTolerance", func() {
		BeforeEach(func() {
			fetcher = NewCPUMetrics(client, logger, namespace, deploymentName, timeWindow)
		})

		Context("with pods exceeding tolerance threshold", func() {
			BeforeEach(func() {
				vectorResult := model.Vector{
					&model.Sample{
						Metric: model.Metric{
							"pod": "consumer-pod-1",
						},
						Value: 1.2,
					},
					&model.Sample{
						Metric: model.Metric{
							"pod": "consumer-pod-2",
						},
						Value: 1.1,
					},
				}
				expectedQuery := `topk(2, sum by(pod) (rate(container_cpu_usage_seconds_total{
  namespace="posthog",
  container="ingestion-consumer"
}[1m0s]))) >
scalar(kube_horizontalpodautoscaler_spec_target_metric{
  horizontalpodautoscaler=~"(keda-hpa-)?ingestion-consumer",
  namespace="posthog",
  metric_name="cpu"
}) / 100 * 1.50 *
avg(kube_pod_container_resource_requests{
  resource="cpu",
  namespace="posthog",
  container="ingestion-consumer"
})`
				client.On("Query", mock.Anything, expectedQuery).Return(vectorResult, nil)
			})

			It("should return top K pods above tolerance", func() {
				usage, err := fetcher.FetchTopKPodsAboveTolerance(ctx, 2, 1.5, "keda-hpa-")

				Expect(err).NotTo(HaveOccurred())
				Expect(usage).To(HaveLen(2))
				Expect(usage["consumer-pod-1"]).To(Equal(1.2))
				Expect(usage["consumer-pod-2"]).To(Equal(1.1))
				client.AssertExpectations(GinkgoT())
			})
		})

		Context("with no pods exceeding tolerance", func() {
			BeforeEach(func() {
				emptyResult := model.Vector{}
				client.On("Query", mock.Anything, mock.Anything).Return(emptyResult, nil)
			})

			It("should return empty map", func() {
				usage, err := fetcher.FetchTopKPodsAboveTolerance(ctx, 2, 1.5, "keda-hpa-")

				Expect(err).NotTo(HaveOccurred())
				Expect(usage).To(BeEmpty())
				client.AssertExpectations(GinkgoT())
			})
		})

		Context("with query error", func() {
			BeforeEach(func() {
				client.On("Query", mock.Anything, mock.Anything).Return(nil, errors.New("query failed"))
			})

			It("should return error", func() {
				usage, err := fetcher.FetchTopKPodsAboveTolerance(ctx, 2, 1.5, "keda-hpa-")

				Expect(err).To(HaveOccurred())
				Expect(err.Error()).To(ContainSubstring("failed to query top K pods above tolerance"))
				Expect(usage).To(BeNil())
			})
		})
	})

	Describe("FetchBottomKPods", func() {
		BeforeEach(func() {
			fetcher = NewCPUMetrics(client, logger, namespace, deploymentName, timeWindow)
		})

		Context("with successful query", func() {
			BeforeEach(func() {
				vectorResult := model.Vector{
					&model.Sample{
						Metric: model.Metric{
							"pod": "consumer-pod-3",
						},
						Value: 0.3,
					},
					&model.Sample{
						Metric: model.Metric{
							"pod": "consumer-pod-4",
						},
						Value: 0.4,
					},
				}
				expectedQuery := `bottomk(2, sum by(pod) (rate(container_cpu_usage_seconds_total{
  namespace="posthog",
  container="ingestion-consumer"
}[1m0s])))`
				client.On("Query", mock.Anything, expectedQuery).Return(vectorResult, nil)
			})

			It("should return bottom K pods", func() {
				usage, err := fetcher.FetchBottomKPods(ctx, 2)

				Expect(err).NotTo(HaveOccurred())
				Expect(usage).To(HaveLen(2))
				Expect(usage["consumer-pod-3"]).To(Equal(0.3))
				Expect(usage["consumer-pod-4"]).To(Equal(0.4))
				client.AssertExpectations(GinkgoT())
			})
		})

		Context("with query error", func() {
			BeforeEach(func() {
				client.On("Query", mock.Anything, mock.Anything).Return(nil, errors.New("timeout"))
			})

			It("should return error", func() {
				usage, err := fetcher.FetchBottomKPods(ctx, 2)

				Expect(err).To(HaveOccurred())
				Expect(err.Error()).To(ContainSubstring("failed to query bottom K pods"))
				Expect(usage).To(BeNil())
			})
		})
	})
})
