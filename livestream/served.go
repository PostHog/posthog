package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"sync/atomic"

	"github.com/getsentry/sentry-go"
	"github.com/hashicorp/golang-lru/v2/expirable"
	"github.com/labstack/echo/v4"
)

type Counter struct {
	EventCount int
	UserCount  int
}

func servedHandler(stats *Stats) func(c echo.Context) error {
	return func(c echo.Context) error {
		userCount := stats.GlobalStore.Len()
		count := stats.Counter.Count()
		resp := Counter{
			EventCount: count,
			UserCount:  userCount,
		}
		return c.JSON(http.StatusOK, resp)
	}
}

func statsHandler(stats *Stats) func(c echo.Context) error {
	return func(c echo.Context) error {

		type resp struct {
			UsersOnProduct int    `json:"users_on_product,omitempty"`
			Error          string `json:"error,omitempty"`
		}

		claims, err := getAuth(c.Request().Header)
		if err != nil {
			return err
		}
		token := fmt.Sprint(claims["api_token"])

		var hash *expirable.LRU[string, string]
		var ok bool
		if hash, ok = stats.Store[token]; !ok {
			resp := resp{
				Error: "no stats",
			}
			return c.JSON(http.StatusOK, resp)
		}

		siteStats := resp{
			UsersOnProduct: hash.Len(),
		}
		return c.JSON(http.StatusOK, siteStats)
	}
}

func streamEventsHandler(log echo.Logger, subChan chan Subscription, filter *Filter) func(c echo.Context) error {
	return func(c echo.Context) error {
		log.Debugf("SSE client connected, ip: %v", c.RealIP())

		var teamId string
		eventType := c.QueryParam("eventType")
		distinctId := c.QueryParam("distinctId")
		geo := c.QueryParam("geo")

		teamIdInt := 0
		token := ""
		geoOnly := false

		if strings.ToLower(geo) == "true" || geo == "1" {
			geoOnly = true
		} else {
			claims, err := getAuth(c.Request().Header)
			if err != nil {
				return err
			}
			teamId = strconv.Itoa(int(claims["team_id"].(float64)))
			token = fmt.Sprint(claims["api_token"])

			if teamId == "" {
				return echo.NewHTTPError(http.StatusBadRequest, "teamId is required unless geo=true")
			}
		}

		var eventTypes []string
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
		defer func() {
			subscription.ShouldClose.Store(true)
			filter.unSubChan <- subscription
		}()

		w := c.Response()
		w.Header().Set("Content-Type", "text/event-stream")
		w.Header().Set("Cache-Control", "no-cache")
		w.Header().Set("Connection", "keep-alive")

		for {
			select {
			case <-c.Request().Context().Done():
				log.Debugf("SSE client disconnected, ip: %v", c.RealIP())
				return nil
			case payload := <-subscription.EventChan:
				jsonData, err := json.Marshal(payload)
				if err != nil {
					sentry.CaptureException(err)
					log.Errorf("Error marshalling payload: %w", err)
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
	}
}
