package decision_test

import (
	"context"
	"errors"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
	"github.com/stretchr/testify/mock"

	"github.com/posthog/pod-rebalancer/pkg/decision"
	"github.com/posthog/pod-rebalancer/pkg/logging"
)

// MockCPUMetricsFetcher is a mock implementation for testing
type MockCPUMetricsFetcher struct {
	mock.Mock
}

func (m *MockCPUMetricsFetcher) FetchCPULimits(ctx context.Context) (float64, error) {
	args := m.Called(ctx)
	return args.Get(0).(float64), args.Error(1)
}

func (m *MockCPUMetricsFetcher) FetchCPURequests(ctx context.Context) (float64, error) {
	args := m.Called(ctx)
	return args.Get(0).(float64), args.Error(1)
}

func (m *MockCPUMetricsFetcher) FetchTopKPodsAboveTolerance(ctx context.Context, k int, toleranceMultiplier float64, hpaPrefix string) (map[string]float64, error) {
	args := m.Called(ctx, k, toleranceMultiplier, hpaPrefix)
	if args.Get(0) != nil {
		return args.Get(0).(map[string]float64), args.Error(1)
	}
	return nil, args.Error(1)
}

func (m *MockCPUMetricsFetcher) FetchBottomKPods(ctx context.Context, k int) (map[string]float64, error) {
	args := m.Called(ctx, k)
	if args.Get(0) != nil {
		return args.Get(0).(map[string]float64), args.Error(1)
	}
	return nil, args.Error(1)
}

var _ = Describe("Engine", func() {
	var (
		engine      *decision.Engine
		mockFetcher *MockCPUMetricsFetcher
		logger      *logging.Logger
		ctx         context.Context
	)

	BeforeEach(func() {
		mockFetcher = new(MockCPUMetricsFetcher)
		logger, _ = logging.New("error") // Use error level to minimize test output
		ctx = context.Background()
	})

	AfterEach(func() {
		mockFetcher.AssertExpectations(GinkgoT())
	})

	Describe("Analyze", func() {
		Context("with standard configuration", func() {
			BeforeEach(func() {
				engine = decision.NewEngine(
					mockFetcher,
					2,           // topK
					1.5,         // toleranceMultiplier
					10.0,        // minimumImprovementPercent
					"keda-hpa-", // hpaPrefix
					logger,
				)
			})

			Context("when pods exceed tolerance and improvement is sufficient", func() {
				It("should recommend rebalancing", func() {
					// Top 2 pods above tolerance: 1.2 and 1.1 cores
					topPods := map[string]float64{
						"pod-high-1": 1.2,
						"pod-high-2": 1.1,
					}
					// Bottom 2 pods: 0.3 and 0.4 cores
					bottomPods := map[string]float64{
						"pod-low-1": 0.3,
						"pod-low-2": 0.4,
					}

					mockFetcher.On("FetchTopKPodsAboveTolerance", ctx, 2, 1.5, "keda-hpa-").Return(topPods, nil)
					mockFetcher.On("FetchBottomKPods", ctx, 2).Return(bottomPods, nil)

					analysis, err := engine.Analyze(ctx)

					Expect(err).NotTo(HaveOccurred())
					Expect(analysis.ShouldRebalance).To(BeTrue())

					// Average top only: (1.2 + 1.1) / 2 = 1.15
					// Average top+bottom: (1.2 + 1.1 + 0.3 + 0.4) / 4 = 0.75
					// Improvement: (1.15 - 0.75) / 1.15 * 100 = 34.8%
					Expect(analysis.Metrics.CurrentAvgTopOnly).To(BeNumerically("~", 1.15, 0.01))
					Expect(analysis.Metrics.CurrentAvgTopBottom).To(BeNumerically("~", 0.75, 0.01))
					Expect(analysis.Metrics.ImprovementPercent).To(BeNumerically("~", 34.8, 0.1))

					Expect(analysis.TargetPods).To(ConsistOf("pod-high-1", "pod-high-2", "pod-low-1", "pod-low-2"))
					Expect(analysis.Reason).To(ContainSubstring("exceeds minimum"))
				})
			})

			Context("when no pods exceed tolerance threshold", func() {
				It("should not recommend rebalancing", func() {
					// No pods above tolerance
					topPods := map[string]float64{}

					mockFetcher.On("FetchTopKPodsAboveTolerance", ctx, 2, 1.5, "keda-hpa-").Return(topPods, nil)
					// Should not call FetchBottomKPods since no top pods found

					analysis, err := engine.Analyze(ctx)

					Expect(err).NotTo(HaveOccurred())
					Expect(analysis.ShouldRebalance).To(BeFalse())
					Expect(analysis.Reason).To(ContainSubstring("No pods exceed tolerance threshold"))
					Expect(analysis.TargetPods).To(BeEmpty())
				})
			})

			Context("when improvement is below minimum threshold", func() {
				It("should not recommend rebalancing", func() {
					// Top 2 pods above tolerance but with small difference
					topPods := map[string]float64{
						"pod-1": 0.9,
						"pod-2": 0.85,
					}
					// Bottom 2 pods not much lower
					bottomPods := map[string]float64{
						"pod-3": 0.8,
						"pod-4": 0.75,
					}

					mockFetcher.On("FetchTopKPodsAboveTolerance", ctx, 2, 1.5, "keda-hpa-").Return(topPods, nil)
					mockFetcher.On("FetchBottomKPods", ctx, 2).Return(bottomPods, nil)

					analysis, err := engine.Analyze(ctx)

					Expect(err).NotTo(HaveOccurred())
					Expect(analysis.ShouldRebalance).To(BeFalse())

					// Average top only: (0.9 + 0.85) / 2 = 0.875
					// Average top+bottom: (0.9 + 0.85 + 0.8 + 0.75) / 4 = 0.825
					// Improvement: (0.875 - 0.825) / 0.875 * 100 = 5.7%
					Expect(analysis.Metrics.ImprovementPercent).To(BeNumerically("<", 10.0))
					Expect(analysis.Reason).To(ContainSubstring("below minimum"))
				})
			})

			Context("when fetching top pods fails", func() {
				It("should return an error", func() {
					expectedErr := errors.New("prometheus query failed")
					mockFetcher.On("FetchTopKPodsAboveTolerance", ctx, 2, 1.5, "keda-hpa-").Return(nil, expectedErr)

					analysis, err := engine.Analyze(ctx)

					Expect(err).To(HaveOccurred())
					Expect(err.Error()).To(ContainSubstring("failed to fetch top K pods above tolerance"))
					Expect(analysis).To(BeNil())
				})
			})

			Context("when fetching bottom pods fails", func() {
				It("should return an error", func() {
					topPods := map[string]float64{"pod-1": 1.2}
					expectedErr := errors.New("prometheus timeout")

					mockFetcher.On("FetchTopKPodsAboveTolerance", ctx, 2, 1.5, "keda-hpa-").Return(topPods, nil)
					mockFetcher.On("FetchBottomKPods", ctx, 2).Return(nil, expectedErr)

					analysis, err := engine.Analyze(ctx)

					Expect(err).To(HaveOccurred())
					Expect(err.Error()).To(ContainSubstring("failed to fetch bottom K pods"))
					Expect(analysis).To(BeNil())
				})
			})
		})

		Context("with custom configuration", func() {
			It("should respect custom tolerance and improvement thresholds", func() {
				engine = decision.NewEngine(
					mockFetcher,
					3,    // topK = 3
					2.0,  // toleranceMultiplier = 2.0
					20.0, // minimumImprovementPercent = 20%
					"",   // no hpaPrefix
					logger,
				)

				topPods := map[string]float64{
					"pod-1": 2.5,
					"pod-2": 2.4,
					"pod-3": 2.3,
				}
				bottomPods := map[string]float64{
					"pod-4": 0.5,
					"pod-5": 0.6,
					"pod-6": 0.7,
				}

				mockFetcher.On("FetchTopKPodsAboveTolerance", ctx, 3, 2.0, "").Return(topPods, nil)
				mockFetcher.On("FetchBottomKPods", ctx, 3).Return(bottomPods, nil)

				analysis, err := engine.Analyze(ctx)

				Expect(err).NotTo(HaveOccurred())
				// Average top: (2.5 + 2.4 + 2.3) / 3 = 2.4
				// Average combined: (2.5 + 2.4 + 2.3 + 0.5 + 0.6 + 0.7) / 6 = 1.5
				// Improvement: (2.4 - 1.5) / 2.4 * 100 = 37.5%
				Expect(analysis.ShouldRebalance).To(BeTrue())
				Expect(analysis.Metrics.ImprovementPercent).To(BeNumerically("~", 37.5, 0.1))
			})
		})
	})
})
