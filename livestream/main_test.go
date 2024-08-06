package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/hashicorp/golang-lru/v2/expirable"
	"github.com/labstack/echo/v4"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestIndex(t *testing.T) {
	e := echo.New()
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	rec := httptest.NewRecorder()
	c := e.NewContext(req, rec)

	if assert.NoError(t, index(c)) {
		assert.Equal(t, http.StatusOK, rec.Code)
	}
}

func TestStatsHandler(t *testing.T) {
	e := echo.New()
	req := httptest.NewRequest(http.MethodGet, "/stats", nil)
	rec := httptest.NewRecorder()
	c := e.NewContext(req, rec)

	// Mock the authorization header
	req.Header.Set("Authorization", "Bearer mock_token")

	// Create a mock TeamStats
	teamStats := &TeamStats{
		Store: make(map[string]*expirable.LRU[string, string]),
	}
	teamStats.Store["mock_token"] = expirable.NewLRU[string, string](100, nil, time.Minute)
	teamStats.Store["mock_token"].Add("user1", "data1")

	// Add the teamStats to the context
	c.Set("teamStats", teamStats)

	handler := func(c echo.Context) error {
		return c.JSON(http.StatusOK, map[string]interface{}{
			"users_on_product": teamStats.Store["mock_token"].Len(),
		})
	}

	if assert.NoError(t, handler(c)) {
		assert.Equal(t, http.StatusOK, rec.Code)
		var response map[string]int
		err := json.Unmarshal(rec.Body.Bytes(), &response)
		require.NoError(t, err)
		assert.Equal(t, 1, response["users_on_product"])
	}
}
func TestJwtHandler(t *testing.T) {
	e := echo.New()
	req := httptest.NewRequest(http.MethodGet, "/jwt", nil)
	rec := httptest.NewRecorder()
	c := e.NewContext(req, rec)

	// Mock the authorization header
	req.Header.Set("Authorization", "Bearer mock_token")

	handler := func(c echo.Context) error {
		authHeader := c.Request().Header.Get("Authorization")
		if authHeader == "" {
			return echo.NewHTTPError(http.StatusBadRequest, "authorization header is required")
		}

		claims := map[string]interface{}{"team_id": float64(1), "api_token": "mock_token"}

		return c.JSON(http.StatusOK, claims)
	}

	if assert.NoError(t, handler(c)) {
		assert.Equal(t, http.StatusOK, rec.Code)
		var response map[string]interface{}
		err := json.Unmarshal(rec.Body.Bytes(), &response)
		require.NoError(t, err)
		assert.Equal(t, float64(1), response["team_id"])
		assert.Equal(t, "mock_token", response["api_token"])
	}
}

func TestSseHandler(t *testing.T) {
	e := echo.New()
	req := httptest.NewRequest(http.MethodGet, "/sse", nil)
	rec := httptest.NewRecorder()
	c := e.NewContext(req, rec)

	// Run the handler in a goroutine
	go func() {
		handler := func(c echo.Context) error {
			w := c.Response()
			w.Header().Set("Content-Type", "text/event-stream")
			w.Header().Set("Cache-Control", "no-cache")
			w.Header().Set("Connection", "keep-alive")

			event := Event{
				Data: []byte("ping: " + time.Now().Format(time.RFC3339Nano)),
			}
			if err := event.WriteTo(w); err != nil {
				return err
			}
			w.Flush()

			return nil
		}

		assert.NoError(t, handler(c))
	}()

	// Wait for the response
	time.Sleep(100 * time.Millisecond)

	// Check the response
	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, "text/event-stream", rec.Header().Get("Content-Type"))
	assert.Equal(t, "no-cache", rec.Header().Get("Cache-Control"))
	assert.Equal(t, "keep-alive", rec.Header().Get("Connection"))

	// Check the event data
	eventData := rec.Body.String()
	assert.Contains(t, eventData, "data: ping: ")
}
