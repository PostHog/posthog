//go:generate mockery
package main

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/labstack/echo/v4"
	"github.com/posthog/posthog/livestream/events"
	"github.com/posthog/posthog/livestream/handlers"
	"github.com/stretchr/testify/assert"
)

func TestIndex(t *testing.T) {
	e := echo.New()
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	rec := httptest.NewRecorder()
	c := e.NewContext(req, rec)

	if assert.NoError(t, handlers.Index(c)) {
		assert.Equal(t, http.StatusOK, rec.Code)
		assert.Equal(t, "RealTime Hog 3000", rec.Body.String())
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
	stats := events.NewStatsKeeper()
	stats.GetStoreForToken("mock_token").Add("user1", events.NoSpaceType{})

	// Add the teamStats to the context
	c.Set("teamStats", stats)

	handler := func(c echo.Context) error {
		return c.JSON(http.StatusOK, map[string]interface{}{
			"users_on_product": stats.GetStoreForToken("mock_token").Len(),
		})
	}

	if assert.NoError(t, handler(c)) {
		assert.Equal(t, http.StatusOK, rec.Code)
		assert.JSONEq(t, `{"users_on_product":1}`, string(rec.Body.Bytes()))
	}
}
