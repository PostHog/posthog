package logging

import (
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

// Metrics holds all Prometheus metrics for the pod rebalancer
type Metrics struct {
	ExecutionsTotal   *prometheus.CounterVec
	PodsAnalyzed      prometheus.Counter
	PodsDeleted       *prometheus.CounterVec
	ExecutionDuration prometheus.Histogram
	LoadVariance      prometheus.Gauge
	APIErrors         *prometheus.CounterVec
}

// NewMetrics creates and registers Prometheus metrics
func NewMetrics() *Metrics {
	return &Metrics{
		ExecutionsTotal: promauto.NewCounterVec(
			prometheus.CounterOpts{
				Name: "rebalancer_executions_total",
				Help: "Total number of rebalancer executions",
			},
			[]string{"status"}, // success, error
		),

		PodsAnalyzed: promauto.NewCounter(
			prometheus.CounterOpts{
				Name: "rebalancer_pods_analyzed_total",
				Help: "Total number of pods analyzed for rebalancing",
			},
		),

		PodsDeleted: promauto.NewCounterVec(
			prometheus.CounterOpts{
				Name: "rebalancer_pods_deleted_total",
				Help: "Total number of pods deleted for rebalancing",
			},
			[]string{"type"}, // most_busy, least_busy
		),

		ExecutionDuration: promauto.NewHistogram(
			prometheus.HistogramOpts{
				Name:    "rebalancer_execution_duration_seconds",
				Help:    "Time spent executing rebalancing cycle",
				Buckets: prometheus.DefBuckets,
			},
		),

		LoadVariance: promauto.NewGauge(
			prometheus.GaugeOpts{
				Name: "rebalancer_load_variance_current",
				Help: "Current load variance across pods (0-1 scale)",
			},
		),

		APIErrors: promauto.NewCounterVec(
			prometheus.CounterOpts{
				Name: "rebalancer_api_errors_total",
				Help: "Total number of API errors encountered",
			},
			[]string{"component"}, // prometheus, kubernetes
		),
	}
}

// RecordExecution records the completion of a rebalancing execution
func (m *Metrics) RecordExecution(success bool, duration float64) {
	status := "success"
	if !success {
		status = "error"
	}

	m.ExecutionsTotal.WithLabelValues(status).Inc()
	m.ExecutionDuration.Observe(duration)
}

// RecordPodsAnalyzed records the number of pods that were analyzed
func (m *Metrics) RecordPodsAnalyzed(count int) {
	m.PodsAnalyzed.Add(float64(count))
}

// RecordPodDeleted records a pod deletion
func (m *Metrics) RecordPodDeleted(podType string) {
	m.PodsDeleted.WithLabelValues(podType).Inc()
}

// RecordLoadVariance records the current load variance
func (m *Metrics) RecordLoadVariance(variance float64) {
	m.LoadVariance.Set(variance)
}

// RecordAPIError records an API error
func (m *Metrics) RecordAPIError(component string) {
	m.APIErrors.WithLabelValues(component).Inc()
}
