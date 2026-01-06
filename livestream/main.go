package main

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/labstack/echo-contrib/echoprometheus"
	"github.com/labstack/echo/v4"
	"github.com/labstack/echo/v4/middleware"
	"github.com/posthog/posthog/livestream/auth"
	"github.com/posthog/posthog/livestream/configs"
	"github.com/posthog/posthog/livestream/events"
	"github.com/posthog/posthog/livestream/geo"
	"github.com/posthog/posthog/livestream/handlers"
	"github.com/posthog/posthog/livestream/metrics"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

func main() {
	configs.InitConfigs("configs", "./configs")

	config, err := configs.LoadConfig()
	if err != nil {
		// TODO capture error to PostHog
		log.Fatalf("Failed to load config: %v", err)
	}

	geolocator, err := geo.NewMaxMindGeoLocator(config.MMDB.Path)
	if err != nil {
		// TODO capture error to PostHog
		log.Fatalf("Failed to open MMDB: %v", err)
	}

	// Setup context for graceful shutdown
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Channel to signal when HTTP server should shutdown
	shutdownHTTP := make(chan struct{})

	// Handle shutdown signals
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)
	go func() {
		<-sigChan
		log.Println("Shutdown signal received, stopping consumers...")
		cancel()
		close(shutdownHTTP)
	}()

	stats := events.NewStatsKeeper()
	sessionStats := events.NewSessionStatsKeeper(config.SessionRecording.MaxLRUEntries, 0)

	phEventChan := make(chan events.PostHogEvent, 10000)
	statsChan := make(chan events.CountEvent, 10000)
	sessionStatsChan := make(chan events.SessionRecordingEvent, 10000)
	subChan := make(chan events.Subscription, 10000)
	unSubChan := make(chan events.Subscription, 10000)

	go stats.KeepStats(statsChan)
	go sessionStats.KeepStats(ctx, sessionStatsChan)

	consumer, err := events.NewPostHogKafkaConsumer(config.Kafka.Brokers, config.Kafka.SecurityProtocol, config.Kafka.GroupID, config.Kafka.Topic, geolocator, phEventChan,
		statsChan, config.Parallelism)
	if err != nil {
		log.Fatalf("Failed to create Kafka consumer: %v", err)
	}
	defer consumer.Close()
	go consumer.Consume()

	if config.Kafka.SessionRecordingEnabled {
		sessionConsumer, err := events.NewSessionRecordingKafkaConsumer(
			config.Kafka.SessionRecordingBrokers, config.Kafka.SessionRecordingSecurityProtocol, config.Kafka.GroupID,
			config.Kafka.SessionRecordingTopic, sessionStatsChan)
		if err != nil {
			log.Printf("Failed to create session recording Kafka consumer: %v", err)
		} else {
			defer sessionConsumer.Close()
			go sessionConsumer.Consume(ctx)
			log.Printf("Session recording consumer started for topic: %s (security_protocol: %s)",
				config.Kafka.SessionRecordingTopic, config.Kafka.SessionRecordingSecurityProtocol)
		}
	}

	go func() {
		ticker := time.NewTicker(7127 * time.Millisecond)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				log.Println("metrics collection shutting down...")
				return
			case <-ticker.C:
				metrics.IncomingQueue.Set(consumer.IncomingRatio())
				metrics.EventQueue.Set(float64(len(phEventChan)) / float64(cap(phEventChan)))
				metrics.StatsQueue.Set(float64(len(statsChan)) / float64(cap(statsChan)))
				metrics.SessionRecordingStatsQueue.Set(float64(len(sessionStatsChan)) / float64(cap(sessionStatsChan)))
				metrics.SubQueue.Set(float64(len(subChan)) / float64(cap(subChan)))
				metrics.UnSubQueue.Set(float64(len(unSubChan)) / float64(cap(unSubChan)))
			}
		}
	}()

	filter := events.NewFilter(subChan, unSubChan, phEventChan)
	go filter.Run()

	// Echo instance
	e := echo.New()

	// Middleware
	e.Use(middleware.RequestID())
	e.Use(middleware.RequestLoggerWithConfig(middleware.RequestLoggerConfig{
		LogLatency:       true,
		LogRemoteIP:      true,
		LogHost:          true,
		LogMethod:        true,
		LogURI:           true,
		LogUserAgent:     true,
		LogStatus:        true,
		LogError:         true,
		LogContentLength: true,
		LogResponseSize:  true,
		LogValuesFunc: func(c echo.Context, v middleware.RequestLoggerValues) error {
			// Build log entry, omitting error field when empty to avoid
			// Grafana/Loki incorrectly categorizing successful requests as errors
			logEntry := map[string]interface{}{
				"time":          v.StartTime.Format(time.RFC3339Nano),
				"id":            c.Response().Header().Get(echo.HeaderXRequestID),
				"remote_ip":     v.RemoteIP,
				"host":          v.Host,
				"method":        v.Method,
				"uri":           v.URI,
				"user_agent":    v.UserAgent,
				"status":        v.Status,
				"latency":       v.Latency.Nanoseconds(),
				"latency_human": v.Latency.String(),
				"bytes_in":      v.ContentLength,
				"bytes_out":     v.ResponseSize,
			}
			if v.Error != nil {
				logEntry["error"] = v.Error.Error()
			}
			jsonBytes, err := json.Marshal(logEntry)
			if err != nil {
				log.Printf("failed to marshal log entry: %v", err)
				return nil
			}
			// Write directly to stdout without log prefix since JSON already has time field
			os.Stdout.Write(append(jsonBytes, '\n'))
			return nil
		},
	}))
	e.Use(middleware.Recover())
	e.Use(middleware.GzipWithConfig(middleware.GzipConfig{
		Level: 9, // Set the compression level to maximum
	}))
	e.Use(echoprometheus.NewMiddlewareWithConfig(
		echoprometheus.MiddlewareConfig{DoNotUseRequestPathFor404: true, Subsystem: "livestream"}))

	e.Use(middleware.CORSWithConfig(middleware.CORSConfig{
		AllowOrigins: config.CORSAllowOrigins,
		AllowMethods: []string{http.MethodGet, http.MethodHead},
	}))

	// Routes
	e.GET("/", handlers.Index)

	// For details why promhttp.Handler won't work: https://github.com/prometheus/client_golang/issues/622
	e.GET("/metrics", echo.WrapHandler(promhttp.InstrumentMetricHandler(
		prometheus.DefaultRegisterer,
		promhttp.HandlerFor(prometheus.DefaultGatherer, promhttp.HandlerOpts{DisableCompression: true}),
	)))

	e.GET("/stats", handlers.StatsHandler(stats, sessionStats))

	e.GET("/events", handlers.StreamEventsHandler(e.Logger, subChan, filter))

	if config.Debug {
		e.GET("/served", handlers.ServedHandler(stats))

		e.GET("/jwt", func(c echo.Context) error {
			claims, err := auth.GetAuth(c.Request().Header)
			if err != nil {
				return err
			}

			return c.JSON(http.StatusOK, claims)
		})

		e.File("/debug", "./index.html")
		e.GET("/debug/sse", func(c echo.Context) error {
			e.Logger.Printf("Map client connected, ip: %v", c.RealIP())

			w := c.Response()
			w.Header().Set("Content-Type", "text/event-stream")
			w.Header().Set("Cache-Control", "no-cache")
			w.Header().Set("Connection", "keep-alive")

			ticker := time.NewTicker(1 * time.Second)
			defer ticker.Stop()
			for {
				select {
				case <-c.Request().Context().Done():
					e.Logger.Printf("SSE client disconnected, ip: %v", c.RealIP())
					return nil
				case <-ticker.C:
					event := handlers.Event{
						Data: []byte("ping: " + time.Now().Format(time.RFC3339Nano)),
					}
					if err := event.WriteTo(w); err != nil {
						return err
					}
					w.Flush()
				}
			}
		})
	}

	// Start HTTP server in goroutine
	go func() {
		if err := e.Start(":8080"); err != nil && err != http.ErrServerClosed {
			e.Logger.Fatal(err)
		}
	}()

	// Wait for shutdown signal
	<-shutdownHTTP

	// Gracefully shutdown HTTP server with timeout
	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer shutdownCancel()
	if err := e.Shutdown(shutdownCtx); err != nil {
		log.Printf("HTTP server shutdown error: %v", err)
	}
	log.Println("HTTP server stopped")
}
