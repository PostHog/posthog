package main

import (
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"strconv"
	"strings"
	"sync/atomic"
	"time"

	"github.com/hashicorp/golang-lru/v2/expirable"
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

	teamStats := &TeamStats{
		Store: make(map[string]*expirable.LRU[string, string]),
	}

	phEventChan := make(chan PostHogEvent)
	statsChan := make(chan PostHogEvent)
	subChan := make(chan Subscription)
	unSubChan := make(chan Subscription)

	go teamStats.keepStats(statsChan)

	consumer, err := NewKafkaConsumer(brokers, groupID, topic, geolocator, phEventChan, statsChan)
	if err != nil {
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

	e.Use(middleware.CORSWithConfig(middleware.CORSConfig{
		AllowOrigins: []string{"*"},
		AllowMethods: []string{http.MethodGet, http.MethodHead},
	}))
	e.File("/", "./index.html")

	// Routes
	e.GET("/", index)

	e.GET("/stats", func(c echo.Context) error {

		type stats struct {
			UsersOnProduct int    `json:"users_on_product,omitempty"`
			Error          string `json:"error,omitempty"`
		}

		authHeader := c.Request().Header.Get("Authorization")
		if authHeader == "" {
			return errors.New("authorization header is required")
		}

		claims, err := decodeAuthToken(authHeader)
		if err != nil {
			return err
		}
		teamIdInt := int(claims["team_id"].(float64))

		token, err := tokenFromTeamId(teamIdInt)
		if err != nil {
			return err
		}

		var hash *expirable.LRU[string, string]
		var ok bool
		if hash, ok = teamStats.Store[token]; !ok {
			resp := stats{
				Error: "no stats",
			}
			return c.JSON(http.StatusOK, resp)
		}

		siteStats := stats{
			UsersOnProduct: hash.Len(),
		}
		return c.JSON(http.StatusOK, siteStats)
	})

	e.GET("/events", func(c echo.Context) error {
		e.Logger.Printf("SSE client connected, ip: %v", c.RealIP())

		teamId := c.QueryParam("teamId")
		eventType := c.QueryParam("eventType")
		distinctId := c.QueryParam("distinctId")
		geo := c.QueryParam("geo")

		teamIdInt := 0
		token := ""
		geoOnly := false

		if strings.ToLower(geo) == "true" || geo == "1" {
			geoOnly = true
		} else {
			teamId = ""

			log.Println("~~~~ Looking for auth header")
			authHeader := c.Request().Header.Get("Authorization")
			if authHeader == "" {
				return errors.New("authorization header is required")
			}

			log.Println("~~~~ decoding auth header")
			claims, err := decodeAuthToken(authHeader)
			if err != nil {
				return err
			}
			teamId = strconv.Itoa(int(claims["team_id"].(float64)))

			log.Printf("~~~~ team found %s", teamId)
			if teamId == "" {
				return errors.New("teamId is required unless geo=true")
			}
		}

		if teamId != "" {
			teamIdInt64, err := strconv.ParseInt(teamId, 10, 0)
			if err != nil {
				return err
			}

			teamIdInt := int(teamIdInt64)
			token, err = tokenFromTeamId(teamIdInt)
			if err != nil {
				return err
			}
		}

		eventTypes := []string{}
		if eventType != "" {
			eventTypes = strings.Split(eventType, ",")
		}

		subscription := Subscription{
			TeamId:      teamIdInt,
			Token:       token,
			ClientId:    c.Response().Header().Get(echo.HeaderXRequestID),
			DistinctId:  distinctId,
			Geo:         geoOnly,
			EventTypes:  eventTypes,
			EventChan:   make(chan interface{}, 100),
			ShouldClose: &atomic.Bool{},
		}

		subChan <- subscription

		w := c.Response()
		w.Header().Set("Content-Type", "text/event-stream")
		w.Header().Set("Cache-Control", "no-cache")
		w.Header().Set("Connection", "keep-alive")

		for {
			select {
			case <-c.Request().Context().Done():
				e.Logger.Printf("SSE client disconnected, ip: %v", c.RealIP())
				filter.unSubChan <- subscription
				subscription.ShouldClose.Store(true)
				return nil
			case payload := <-subscription.EventChan:
				jsonData, err := json.Marshal(payload)
				if err != nil {
					log.Println("Error marshalling payload", err)
					continue
				}

				event := Event{
					Data: jsonData,
				}
				if err := event.WriteTo(w); err != nil {
					return err
				}
				w.Flush()
			}
		}
	})

	e.GET("/jwt", func(c echo.Context) error {
		authHeader := c.Request().Header.Get("Authorization")
		if authHeader == "" {
			return errors.New("authorization header is required")
		}

		claims, err := decodeAuthToken(authHeader)
		if err != nil {
			return err
		}

		return c.JSON(http.StatusOK, claims)
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
		e.Logger.Fatal(e.StartAutoTLS(":443"))
	}
}
