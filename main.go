package main

import (
	"errors"
	"log"
	"net/http"
	"time"

	"github.com/labstack/echo/v4"
	"github.com/labstack/echo/v4/middleware"
	"github.com/spf13/viper"
)

func main() {
	loadConfigs()

	mmdb := viper.GetString("mmdb.path")
	if mmdb == "" {
		log.Fatal("mmdb.path must be set")
	}

	geolocator, err := NewGeoLocator(mmdb)
	if err != nil {
		log.Fatalf("Failed to open MMDB: %v", err)
	}

	brokers := viper.GetString("kafka.brokers")
	if brokers == "" {
		log.Fatal("kafka.brokers must be set")
	}

	topic := viper.GetString("kafka.topic")
	if topic == "" {
		log.Fatal("kafka.topic must be set")
	}

	groupID := viper.GetString("kafka.group_id")

	consumer, err := NewKafkaConsumer(brokers, groupID, topic, geolocator)
	if err != nil {
		log.Fatalf("Failed to create Kafka consumer: %v", err)
	}
	defer consumer.Close()

	go consumer.Consume()

	// Echo instance
	e := echo.New()

	// Middleware
	e.Use(middleware.Logger())
	e.Use(middleware.Recover())
	e.File("/", "./index.html")

	// Routes
	e.GET("/", index)

	e.GET("/events", func(c echo.Context) error {
		e.Logger.Printf("SSE client connected, ip: %v", c.RealIP())

		w := c.Response()
		w.Header().Set("Content-Type", "text/event-stream")
		w.Header().Set("Cache-Control", "no-cache")
		w.Header().Set("Connection", "keep-alive")

		teamId := c.QueryParam("teamId")
		eventType := c.QueryParam("eventType")
		distinctId := c.QueryParam("distinctId")

		ticker := time.NewTicker(1 * time.Second)
		defer ticker.Stop()
		for {
			select {
			case <-c.Request().Context().Done():
				e.Logger.Printf("SSE client disconnected, ip: %v", c.RealIP())
				return nil
			case <-ticker.C:
				event := Event{
					Data: []byte("ping: " + time.Now().Format(time.RFC3339Nano) + "\nparameters: " +
						"\n\tteamId: " + teamId +
						"\n\teventType: " + eventType +
						"\n\tdistinctId: " + distinctId),
				}
				if err := event.WriteTo(w); err != nil {
					return err
				}
				w.Flush()
			}
		}
	})

	e.GET("/sse", func(c echo.Context) error {
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

	if !viper.GetBool("prod") {
		e.Logger.Fatal(e.Start(":8080"))
	} else {
		// Start Tailnet
		tailNetServer, err := initTailNetServer()
		if err != nil {
			e.Logger.Panic("cannot start tailnet server")
		}

		// Start server
		s := http.Server{
			Handler: e,
		}

		if err := s.Serve(*tailNetServer); err != nil && !errors.Is(err, http.ErrServerClosed) {
			e.Logger.Fatal(err)
		}
	}
}

// Handler
func index(c echo.Context) error {
	return c.String(http.StatusOK, "RealTime Hog 3000")
}
