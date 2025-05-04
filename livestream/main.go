package main

import (
	"log"
	"net/http"
	"time"

	"github.com/labstack/echo-contrib/echoprometheus"
	"github.com/labstack/echo/v4"
	"github.com/labstack/echo/v4/middleware"
	"github.com/posthog/posthog/livestream/auth"
	"github.com/posthog/posthog/livestream/events"
	"github.com/posthog/posthog/livestream/geo"
	"github.com/posthog/posthog/livestream/handlers"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"github.com/spf13/viper"
)

func main() {
	loadConfigs()

	isDebug := viper.GetBool("debug")
	mmdb := viper.GetString("mmdb.path")
	if mmdb == "" {
		// TODO capture error to PostHog
		log.Fatal("mmdb.path must be set")
	}
	brokers := viper.GetString("kafka.brokers")
	if brokers == "" {
		// TODO capture error to PostHog
		log.Fatal("kafka.brokers must be set")
	}
	topic := viper.GetString("kafka.topic")
	if topic == "" {
		// TODO capture error to PostHog
		log.Fatal("kafka.topic must be set")
	}
	groupID := viper.GetString("kafka.group_id")
	if groupID == "" {
		// TODO capture error to PostHog
		log.Fatal("kafka.group_id must be set")
	}
	parallelism := viper.GetInt("parallelism")
	if parallelism == 0 {
		parallelism = 1
	}

	geolocator, err := geo.NewMaxMindGeoLocator(mmdb)
	if err != nil {
		// TODO capture error to PostHog
		log.Fatalf("Failed to open MMDB: %v", err)
	}

	stats := events.NewStatsKeeper()

	phEventChan := make(chan events.PostHogEvent, 10000)
	statsChan := make(chan events.CountEvent, 10000)
	subChan := make(chan events.Subscription, 10000)
	unSubChan := make(chan events.Subscription, 10000)

	go stats.KeepStats(statsChan)

	kafkaSecurityProtocol := "SSL"
	if isDebug {
		kafkaSecurityProtocol = "PLAINTEXT"
	}
	consumer, err := events.NewPostHogKafkaConsumer(brokers, kafkaSecurityProtocol, groupID, topic, geolocator, phEventChan,
		statsChan, parallelism)
	if err != nil {
		// TODO capture error to PostHog
		log.Fatalf("Failed to create Kafka consumer: %v", err)
	}
	defer consumer.Close()
	go consumer.Consume()

	filter := events.NewFilter(subChan, unSubChan, phEventChan)
	go filter.Run()

	// Echo instance
	e := echo.New()

	// Middleware
	e.Use(middleware.Logger())
	e.Use(middleware.Recover())
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
	e.GET("/", handlers.Index)

	// For details why promhttp.Handler won't work: https://github.com/prometheus/client_golang/issues/622
	e.GET("/metrics", echo.WrapHandler(promhttp.InstrumentMetricHandler(
		prometheus.DefaultRegisterer,
		promhttp.HandlerFor(prometheus.DefaultGatherer, promhttp.HandlerOpts{DisableCompression: true}),
	)))

	e.GET("/stats", handlers.StatsHandler(stats))

	e.GET("/events", handlers.StreamEventsHandler(e.Logger, subChan, filter))

	if isDebug {
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

	e.Logger.Fatal(e.Start(":8080"))
}
