package handlers

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"sync/atomic"
	"time"

	"github.com/labstack/echo/v4"
	"github.com/posthog/posthog/livestream/auth"
	"github.com/posthog/posthog/livestream/events"
	"github.com/redis/go-redis/v9"
)

func Index(c echo.Context) error {
	return c.String(http.StatusOK, "RealTime Hog 3000")
}

type Counter struct {
	EventCount int
	UserCount  int
}

func ServedHandler(stats *events.Stats) func(c echo.Context) error {
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

func StatsHandler(stats *events.Stats, sessionStats *events.SessionStats) func(c echo.Context) error {
	return func(c echo.Context) error {

		type resp struct {
			UsersOnProduct   int    `json:"users_on_product,omitempty"`
			ActiveRecordings int    `json:"active_recordings,omitempty"`
			Error            string `json:"error,omitempty"`
		}

		_, token, err := auth.GetAuthClaims(c.Request().Header)
		if err != nil {
			return c.JSON(http.StatusUnauthorized, resp{Error: "wrong token claims"})
		}

		userStore := stats.GetExistingStoreForToken(token)
		sessionCount := sessionStats.CountForToken(token)

		if userStore == nil && sessionCount == 0 {
			return c.JSON(http.StatusOK, resp{Error: "no stats"})
		}

		siteStats := resp{}
		if userStore != nil {
			siteStats.UsersOnProduct = userStore.Len()
		}
		if sessionCount != 0 {
			siteStats.ActiveRecordings = sessionCount
		}
		return c.JSON(http.StatusOK, siteStats)
	}
}

func NotificationsHandler(redisClient *redis.Client) func(c echo.Context) error {
	return func(c echo.Context) error {
		teamID, userID, _, err := auth.GetAuthClaimsWithUserID(c.Request().Header)
		if err != nil || teamID == 0 || userID == 0 {
			return echo.NewHTTPError(http.StatusUnauthorized, "invalid token")
		}

		ctx := c.Request().Context()
		channel := fmt.Sprintf("notifications:%d:%d", teamID, userID)
		bufferKey := fmt.Sprintf("notification_buffer:%d:%d", teamID, userID)

		pubsub := redisClient.Subscribe(ctx, channel)
		defer pubsub.Close()

		w := c.Response()
		w.Header().Set("Content-Type", "text/event-stream")
		w.Header().Set("Cache-Control", "no-cache")
		w.Header().Set("Connection", "keep-alive")

		buffered, err := redisClient.LRange(ctx, bufferKey, 0, 49).Result()
		if err == nil && len(buffered) > 0 {
			for i := len(buffered) - 1; i >= 0; i-- {
				event := Event{Data: []byte(buffered[i])}
				if err := event.WriteTo(w); err != nil {
					return err
				}
			}
			w.Flush()
		}

		msgCh := pubsub.Channel()
		heartbeat := time.NewTicker(15 * time.Second)
		defer heartbeat.Stop()
		timeout := time.After(30 * time.Minute)

		for {
			select {
			case <-timeout:
				return nil
			case <-ctx.Done():
				return nil
			case msg := <-msgCh:
				if msg == nil {
					continue
				}
				event := Event{Data: []byte(msg.Payload)}
				if err := event.WriteTo(w); err != nil {
					return err
				}
				w.Flush()
			case <-heartbeat.C:
				event := Event{Comment: []byte("heartbeat")}
				if err := event.WriteTo(w); err != nil {
					return err
				}
				w.Flush()
			}
		}
	}
}

var subID uint64 = 1

func StreamEventsHandler(log echo.Logger, subChan chan events.Subscription, filter *events.Filter) func(c echo.Context) error {
	return func(c echo.Context) error {
		log.Debugf("SSE client connected, ip: %v", c.RealIP())

		var (
			teamID  int
			token   string
			geoOnly bool
			err     error
		)

		teamID, token, err = auth.GetAuthClaims(c.Request().Header)
		if err != nil || token == "" || teamID == 0 {
			return echo.NewHTTPError(http.StatusUnauthorized, "wrong token")
		}

		eventType := c.QueryParam("eventType")
		distinctId := c.QueryParam("distinctId")
		geo := c.QueryParam("geo")

		if strings.ToLower(geo) == "true" || geo == "1" {
			geoOnly = true
		}

		var columns []string
		if _, hasColumns := c.QueryParams()["columns"]; hasColumns {
			columnsParam := strings.TrimSpace(c.QueryParam("columns"))
			if columnsParam != "" {
				columns = strings.Split(columnsParam, ",")
				for i, col := range columns {
					columns[i] = strings.TrimSpace(col)
				}
			} else {
				columns = []string{}
			}
		}

		var eventTypes []string
		if eventType != "" {
			eventTypes = strings.Split(eventType, ",")
		}

		subscription := events.Subscription{
			SubID:         atomic.AddUint64(&subID, 1),
			TeamId:        teamID,
			Token:         token,
			DistinctId:    distinctId,
			Geo:           geoOnly,
			Columns:       columns,
			EventTypes:    eventTypes,
			EventChan:     make(chan interface{}, 100),
			ShouldClose:   &atomic.Bool{},
			DroppedEvents: &atomic.Uint64{},
		}

		subChan <- subscription
		defer func() {
			subscription.ShouldClose.Store(true)
			filter.UnSubChan <- subscription
		}()

		w := c.Response()
		w.Header().Set("Content-Type", "text/event-stream")
		w.Header().Set("Cache-Control", "no-cache")
		w.Header().Set("Connection", "keep-alive")
		timeout := time.After(30 * time.Minute)
		for {
			select {
			case <-timeout:
				log.Debug("SSE connection to be terminated after timeout")
				return nil
			case <-c.Request().Context().Done():
				log.Debugf("SSE client disconnected, ip: %v", c.RealIP())
				return nil
			case payload := <-subscription.EventChan:
				jsonData, err := json.Marshal(payload)
				if err != nil {
					// TODO capture error to PostHog
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
