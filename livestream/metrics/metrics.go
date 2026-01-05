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

	IncomingQueue = promauto.NewGauge(prometheus.GaugeOpts{
		Name: "livestream_incoming_queue_use_ratio",
		Help: "How much of incoming queue is used",
	})
	EventQueue = promauto.NewGauge(prometheus.GaugeOpts{
		Name: "livestream_event_queue_use_ratio",
		Help: "How much of parsed event queue is used",
	})
	StatsQueue = promauto.NewGauge(prometheus.GaugeOpts{
		Name: "livestream_stats_queue_use_ratio",
		Help: "How much of stats queue is used",
	})
	SubQueue = promauto.NewGauge(prometheus.GaugeOpts{
		Name: "livestream_sub_queue_use_ratio",
		Help: "How much of sub queue is used (a connection create subscription)",
	})
	UnSubQueue = promauto.NewGauge(prometheus.GaugeOpts{
		Name: "livestream_unsub_queue_use_ratio",
		Help: "How much of unsub queue is used (disconnecting removes subscription)",
	})
	SubTotal = promauto.NewGauge(prometheus.GaugeOpts{
		Name: "livestream_active_event_subscriptions_total",
		Help: "How many active event subscriptions we have",
	})

	SessionRecordingMsgConsumed = promauto.NewCounterVec(
		prometheus.CounterOpts{
			Name: "livestream_session_recording_kafka_consumed_total",
			Help: "The total number of consumed session recording messages",
		},
		[]string{"partition"},
	)
	SessionRecordingTimeoutConsume = promauto.NewCounter(prometheus.CounterOpts{
		Name: "livestream_session_recording_kafka_timeout_total",
		Help: "The total number of session recording consume timeouts",
	})
	SessionRecordingConnectFailure = promauto.NewCounter(prometheus.CounterOpts{
		Name: "livestream_session_recording_kafka_connect_failure_total",
		Help: "The total number of failed session recording connect attempts",
	})
	SessionRecordingHandledEvents = promauto.NewCounter(prometheus.CounterOpts{
		Name: "livestream_session_recording_events_total",
		Help: "The total number of handled session recording events",
	})
	SessionRecordingStatsQueue = promauto.NewGauge(prometheus.GaugeOpts{
		Name: "livestream_session_recording_stats_queue_use_ratio",
		Help: "How much of session recording stats queue is used",
	})
	SessionRecordingDroppedMessages = promauto.NewCounter(prometheus.CounterOpts{
		Name: "livestream_session_recording_dropped_messages_total",
		Help: "The total number of session recording messages dropped due to missing headers",
	})

	// Session stats LRU metrics
	SessionRecordingLRUSize = promauto.NewGauge(prometheus.GaugeOpts{
		Name: "livestream_session_recording_lru_size",
		Help: "Current number of unique sessions in the LRU cache",
	})
	SessionRecordingLRUEvictions = promauto.NewCounter(prometheus.CounterOpts{
		Name: "livestream_session_recording_lru_evictions_total",
		Help: "Total number of sessions evicted from LRU (by TTL or capacity)",
	})
	SessionRecordingTokenCount = promauto.NewGauge(prometheus.GaugeOpts{
		Name: "livestream_session_recording_token_count",
		Help: "Number of unique tokens being tracked",
	})
)
