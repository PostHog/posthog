package main

import (
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

var (
	msgConsumed = promauto.NewCounter(prometheus.CounterOpts{
		Name: "livestream_kafka_consumed_total",
		Help: "The total number of processed events",
	})
	timeoutConsume = promauto.NewCounter(prometheus.CounterOpts{
		Name: "livestream_kafka_timeout_total",
		Help: "The total number of timeout consume",
	})
	connectFailure = promauto.NewCounter(prometheus.CounterOpts{
		Name: "livestream_kafka_connect_failure_total",
		Help: "The total number of failed connect attempts",
	})
	handledEvents = promauto.NewCounter(prometheus.CounterOpts{
		Name: "livestream_ph_events_total",
		Help: "The total number of handled PostHog events, less or equal than consumed",
	})
)
