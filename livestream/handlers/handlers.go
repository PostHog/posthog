package handlers

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strings"
	"sync/atomic"
	"time"

	"github.com/labstack/echo/v4"
	"github.com/posthog/posthog/livestream/auth"
	"github.com/posthog/posthog/livestream/events"
	"github.com/posthog/posthog/livestream/metrics"
	"github.com/redis/rueidis"
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

func StatsHandler(stats *events.Stats, sessionStats *events.SessionStats, redisStore *events.StatsInRedis) func(c echo.Context) error {
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
		if _, err := auth.CheckAccess(c.Request().Context(), c.Request().Header); err != nil {
			return err
		}

		if redisStore != nil {
			ctx := c.Request().Context()
			userCount, userErr := redisStore.GetUserCount(ctx, token)
			sessionCount, sessionErr := redisStore.GetSessionCount(ctx, token)

			if userErr == nil && sessionErr == nil {
				if userCount == 0 && sessionCount == 0 {
					return c.JSON(http.StatusOK, resp{Error: "no stats"})
				}

				siteStats := resp{}
				siteStats.UsersOnProduct = int(userCount)
				siteStats.ActiveRecordings = int(sessionCount)

				return c.JSON(http.StatusOK, siteStats)
			}

			log.Printf("Redis read failed, falling back to local LRU: users_err=%v sessions_err=%v", userErr, sessionErr)
		}

		// Fallback to local LRU until V2 migration is complete
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

var subID uint64 = 1

// An error from apply ends the stream the same way a denied check does.
func periodicAccessChecks(
	ctx context.Context,
	header http.Header,
	interval time.Duration,
	apply func(*auth.PropertyRestrictions) error,
) <-chan error {
	errors := make(chan error, 1)
	go func() {
		ticker := time.NewTicker(interval)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				restrictions, err := auth.CheckAccess(ctx, header)
				if err == nil && apply != nil {
					err = apply(restrictions)
				}
				if err != nil {
					select {
					case errors <- err:
					case <-ctx.Done():
					}
					return
				}
			}
		}
	}()
	return errors
}

func restrictedFilterError(key string) error {
	return echo.NewHTTPError(http.StatusBadRequest, fmt.Sprintf("property filter references a restricted property: %s", key))
}

func StreamEventsHandler(log echo.Logger, subChan chan events.Subscription, unSubChan chan events.Subscription) func(c echo.Context) error {
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
		restrictions, err := auth.CheckAccess(c.Request().Context(), c.Request().Header)
		if err != nil {
			return err
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

		propertyFilters := parsePropertyFilters(c.QueryParam("properties"), c.QueryParams()["property"])
		if key := events.RestrictedFilterKey(propertyFilters, restrictions); key != "" {
			return restrictedFilterError(key)
		}
		pathCleaner := events.NewPathCleanerFromJSON(c.QueryParam("pathCleaning"))

		currentRestrictions := &atomic.Pointer[auth.PropertyRestrictions]{}
		currentRestrictions.Store(restrictions)

		subscription := events.Subscription{
			SubID:           atomic.AddUint64(&subID, 1),
			TeamId:          teamID,
			Token:           token,
			DistinctId:      distinctId,
			Geo:             geoOnly,
			Columns:         columns,
			EventTypes:      eventTypes,
			PropertyFilters: propertyFilters,
			Restrictions:    currentRestrictions,
			PathCleaner:     pathCleaner,
			EventChan:       make(chan interface{}, 100),
			ShouldClose:     &atomic.Bool{},
			DroppedEvents:   &atomic.Uint64{},
		}

		subChan <- subscription
		defer func() {
			subscription.ShouldClose.Store(true)
			unSubChan <- subscription
		}()

		w := c.Response()
		w.Header().Set("Content-Type", "text/event-stream")
		w.Header().Set("Cache-Control", "no-cache")
		w.Header().Set("Connection", "keep-alive")
		timeout := time.After(30 * time.Minute)
		accessContext, cancelAccessCheck := context.WithCancel(c.Request().Context())
		defer cancelAccessCheck()
		accessErrors := periodicAccessChecks(accessContext, c.Request().Header.Clone(), 30*time.Second,
			func(fresh *auth.PropertyRestrictions) error {
				currentRestrictions.Store(fresh)
				if key := events.RestrictedFilterKey(propertyFilters, fresh); key != "" {
					return restrictedFilterError(key)
				}
				return nil
			})
		for {
			select {
			case err := <-accessErrors:
				log.Warnf("Live stream authorization check failed: %v", err)
				return nil
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

func parsePropertyFilters(propertiesJSON string, legacy []string) []events.CompiledPropertyFilter {
	filters := parsePropertyFiltersJSON(propertiesJSON)
	filters = append(filters, parseLegacyPropertyFilters(legacy)...)
	if len(filters) == 0 {
		return nil
	}
	return filters
}

func parsePropertyFiltersJSON(raw string) []events.CompiledPropertyFilter {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return nil
	}
	dec := json.NewDecoder(strings.NewReader(raw))
	dec.UseNumber()
	var payloads []struct {
		Key      string      `json:"key"`
		Operator string      `json:"operator"`
		Value    interface{} `json:"value"`
	}
	if err := dec.Decode(&payloads); err != nil {
		return nil
	}
	out := make([]events.CompiledPropertyFilter, 0, len(payloads))
	for _, p := range payloads {
		if p.Key == "" || p.Operator == "" {
			continue
		}
		out = append(out, events.NewCompiledPropertyFilter(p.Key, p.Operator, normalizeFilterValues(p.Value)))
	}
	return out
}

func parseLegacyPropertyFilters(raw []string) []events.CompiledPropertyFilter {
	if len(raw) == 0 {
		return nil
	}
	grouped := make(map[string][]string, len(raw))
	order := make([]string, 0, len(raw))
	for _, entry := range raw {
		k, v, ok := strings.Cut(entry, "=")
		if !ok || k == "" {
			continue
		}
		if _, seen := grouped[k]; !seen {
			order = append(order, k)
		}
		grouped[k] = append(grouped[k], v)
	}
	out := make([]events.CompiledPropertyFilter, 0, len(order))
	for _, k := range order {
		out = append(out, events.NewCompiledPropertyFilter(k, events.OpExact, grouped[k]))
	}
	return out
}

func normalizeFilterValues(value interface{}) []string {
	switch v := value.(type) {
	case nil:
		return nil
	case []interface{}:
		out := make([]string, 0, len(v))
		for _, item := range v {
			if item != nil {
				out = append(out, fmt.Sprint(item))
			}
		}
		return out
	default:
		return []string{fmt.Sprint(v)}
	}
}

func NotificationsHandler(redisClient rueidis.Client) func(c echo.Context) error {
	return func(c echo.Context) error {
		claims, err := auth.ParseAuthClaims(c.Request().Header)
		if err != nil {
			return echo.NewHTTPError(http.StatusUnauthorized, "invalid token")
		}
		if claims.OrganizationID == "" || claims.UserID == 0 {
			// Old tokens without organization_id/user_id — no-op until all tokens refresh
			return c.NoContent(http.StatusNoContent)
		}
		if _, err := auth.CheckAccess(c.Request().Context(), c.Request().Header); err != nil {
			return err
		}
		ctx, cancel := context.WithCancel(c.Request().Context())
		defer cancel()

		metrics.NotificationSubs.Inc()
		defer metrics.NotificationSubs.Dec()

		channel := fmt.Sprintf("notifications:%s", claims.OrganizationID)

		// Absorbs publish-rate bursts; drops on overflow to avoid blocking rueidis.
		msgCh := make(chan string, 1000)
		errCh := make(chan error, 1)

		// Receive respects ctx cancellation — goroutine exits when handler returns.
		go func() {
			errCh <- redisClient.Receive(ctx, redisClient.B().Ssubscribe().Channel(channel).Build(), func(msg rueidis.PubSubMessage) {
				metrics.NotificationMessagesReceivedTotal.Inc()
				select {
				case msgCh <- msg.Message:
				default:
					metrics.NotificationMessagesDroppedTotal.WithLabelValues("buffer_full").Inc()
					log.Printf("Notification dropped for user %d: channel buffer full", claims.UserID)
				}
			})
		}()

		w := c.Response()
		w.Header().Set("Content-Type", "text/event-stream")
		w.Header().Set("Cache-Control", "no-cache")
		w.Header().Set("Connection", "keep-alive")

		heartbeat := time.NewTicker(15 * time.Second)
		defer heartbeat.Stop()
		timeout := time.After(30 * time.Minute)
		accessErrors := periodicAccessChecks(ctx, c.Request().Header.Clone(), 15*time.Second, nil)

		for {
			select {
			case <-timeout:
				return nil
			case <-ctx.Done():
				return nil
			case err := <-errCh:
				if err != nil {
					log.Printf("Redis subscription error: %v", err)
				}
				return nil
			case err := <-accessErrors:
				log.Printf("Live stream authorization check failed: %v", err)
				return nil
			case msg := <-msgCh:
				cleaned, ok, reason := filterNotificationForUser(msg, claims.UserID)
				if !ok {
					metrics.NotificationMessagesDroppedTotal.WithLabelValues(reason).Inc()
					continue
				}
				event := Event{Data: []byte(cleaned)}
				if err := event.WriteTo(w); err != nil {
					return err
				}
				w.Flush()
				metrics.NotificationMessagesDeliveredTotal.Inc()
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

// filterNotificationForUser decides whether a message should be delivered to
// the SSE client for userID. When the message is dropped, the reason is
// returned so callers can emit a labeled metric.
func filterNotificationForUser(payload string, userID int) (cleaned string, deliver bool, dropReason string) {
	var data map[string]interface{}
	if err := json.Unmarshal([]byte(payload), &data); err != nil {
		return "", false, "malformed_payload"
	}

	resolvedIDs, ok := data["resolved_user_ids"]
	if !ok {
		return "", false, "malformed_payload"
	}

	ids, ok := resolvedIDs.([]interface{})
	if !ok {
		return "", false, "malformed_payload"
	}

	for _, id := range ids {
		if num, ok := id.(float64); ok && int(num) == userID {
			delete(data, "resolved_user_ids")
			out, err := json.Marshal(data)
			if err != nil {
				return "", false, "marshal_error"
			}
			return string(out), true, ""
		}
	}

	return "", false, "wrong_user"
}
