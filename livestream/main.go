package main

import (
	"errors"
	"log"
	"net/http"
	"time"

	"github.com/getsentry/sentry-go"
	"github.com/labstack/echo-contrib/echoprometheus"
	"github.com/labstack/echo/v4"
	"github.com/labstack/echo/v4/middleware"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"github.com/spf13/viper"
)

func main() {
	loadConfigs()

	isProd := viper.GetBool("prod")

	err := sentry.Init(sentry.ClientOptions{
		Dsn:              viper.GetString("sentry.dsn"),
		Debug:            !isProd,
		AttachStacktrace: true,
	})
	if err != nil {
		sentry.CaptureException(err)
		log.Fatalf("sentry.Init: %s", err)
	}
	// Flush buffered events before the program terminates.
	// Set the timeout to the maximum duration the program can afford to wait.
	defer sentry.Flush(2 * time.Second)

	mmdb := viper.GetString("mmdb.path")
	if mmdb == "" {
		sentry.CaptureException(errors.New("mmdb.path must be set"))
		log.Fatal("mmdb.path must be set")
	}
	brokers := viper.GetString("kafka.brokers")
	if brokers == "" {
		sentry.CaptureException(errors.New("kafka.brokers must be set"))
		log.Fatal("kafka.brokers must be set")
	}
	topic := viper.GetString("kafka.topic")
	if topic == "" {
		sentry.CaptureException(errors.New("kafka.topic must be set"))
		log.Fatal("kafka.topic must be set")
	}
	groupID := viper.GetString("kafka.group_id")
	if groupID == "" {
		sentry.CaptureException(errors.New("kafka.group_id must be set"))
		log.Fatal("kafka.group_id must be set")
	}

	geolocator, err := NewMaxMindGeoLocator(mmdb)
	if err != nil {
		sentry.CaptureException(err)
		log.Fatalf("Failed to open MMDB: %v", err)
	}

	stats := newStatsKeeper()

	phEventChan := make(chan PostHogEvent, 1000)
	statsChan := make(chan CountEvent, 1000)
	subChan := make(chan Subscription, 1000)
	unSubChan := make(chan Subscription, 1000)

	go stats.keepStats(statsChan)

	kafkaSecurityProtocol := "SSL"
	if !isProd {
		kafkaSecurityProtocol = "PLAINTEXT"
	}
	consumer, err := NewPostHogKafkaConsumer(brokers, kafkaSecurityProtocol, groupID, topic, geolocator, phEventChan, statsChan)
	if err != nil {
		sentry.CaptureException(err)
		log.Fatalf("Failed to create Kafka consumer: %v", err)
	}
	defer consumer.Close()
	go consumer.Consume()

	filter := NewFilter(subChan, unSubChan, phEventChan)
	go filter.Run()

	// Echo instance
	e := echo.New()

	// Middleware
	e.Use(middleware.Logger())
	e.Use(middleware.Recover())
	e.Use(middleware.RequestID())
	e.Use(middleware.GzipWithConfig(middleware.GzipConfig{
		Level: 9, // Set compression level to maximum
	}))
	e.Use(echoprometheus.NewMiddlewareWithConfig(
		echoprometheus.MiddlewareConfig{DoNotUseRequestPathFor404: true, Subsystem: "livestream"}))

	e.Use(middleware.CORSWithConfig(middleware.CORSConfig{
		AllowOrigins: []string{"*"},
		AllowMethods: []string{http.MethodGet, http.MethodHead},
	}))

	// Routes
	e.GET("/", index)

	// For details why promhttp.Handler won't work: https://github.com/prometheus/client_golang/issues/622
	e.GET("/metrics", echo.WrapHandler(promhttp.InstrumentMetricHandler(
		prometheus.DefaultRegisterer,
		promhttp.HandlerFor(prometheus.DefaultGatherer, promhttp.HandlerOpts{DisableCompression: true}),
	)))

	e.GET("/served", servedHandler(stats))

	e.GET("/stats", statsHandler(stats))

	e.GET("/events", streamEventsHandler(e.Logger, subChan, filter))

	if !isProd {
		e.GET("/jwt", func(c echo.Context) error {
			claims, err := getAuth(c.Request().Header)
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
					event := Event{
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

	e.Logger.Fatal(e.Start(":8080"))
}
