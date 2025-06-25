package metrics

import (
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

var (
	MsgConsumed = promauto.NewCounterVec(
		prometheus.CounterOpts{
			Name: "livestream_kafka_consumed_total",
			Help: "The total number of processed events",
		},
		[]string{"partition"},
	)
	TimeoutConsume = promauto.NewCounter(prometheus.CounterOpts{
		Name: "livestream_kafka_timeout_total",
		Help: "The total number of consume timeouts",
	})
	ConnectFailure = promauto.NewCounter(prometheus.CounterOpts{
		Name: "livestream_kafka_connect_failure_total",
		Help: "The total number of failed connect attempts",
	})
	HandledEvents = promauto.NewCounter(prometheus.CounterOpts{
		Name: "livestream_ph_events_total",
		Help: "The total number of handled PostHog events, less than or equal to consumed",
	})
)
