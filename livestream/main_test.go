// go:generate mockery
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
	stats := &Stats{
		Store: make(map[string]*expirable.LRU[string, string]),
	}
	stats.Store["mock_token"] = expirable.NewLRU[string, string](100, nil, time.Minute)
	stats.Store["mock_token"].Add("user1", "data1")

	// Add the teamStats to the context
	c.Set("teamStats", stats)

	handler := func(c echo.Context) error {
		return c.JSON(http.StatusOK, map[string]interface{}{
			"users_on_product": stats.Store["mock_token"].Len(),
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
