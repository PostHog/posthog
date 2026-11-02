//go:generate mockery
package main

import (
	"net"
	"net/http"
	"net/http/httptest"
	"runtime/debug"
	"testing"

	"github.com/labstack/echo/v4"
	"github.com/posthog/posthog/livestream/events"
	"github.com/posthog/posthog/livestream/handlers"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
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
		assert.JSONEq(t, `{"users_on_product":1}`, rec.Body.String())
	}
}

func TestMultipathTCPIsDisabledByDefault(t *testing.T) {
	buildInfo, ok := debug.ReadBuildInfo()
	require.True(t, ok, "build info unavailable")

	var defaults string
	for _, setting := range buildInfo.Settings {
		if setting.Key == "DefaultGODEBUG" {
			defaults += setting.Value
		}
	}
	require.Contains(t, defaults, "multipathtcp=0", "go.mod must keep godebug multipathtcp=0")

	var lc net.ListenConfig
	assert.False(t, lc.MultipathTCP())
}

func TestNewListenerAcceptsConnections(t *testing.T) {
	listener, err := newListener(t.Context(), "127.0.0.1:0")
	require.NoError(t, err)
	t.Cleanup(func() { _ = listener.Close() })

	accepted := make(chan error, 1)
	go func() {
		conn, err := listener.Accept()
		if err != nil {
			accepted <- err
			return
		}
		accepted <- conn.Close()
	}()

	conn, err := net.Dial("tcp", listener.Addr().String())
	require.NoError(t, err)
	require.NoError(t, conn.Close())
	require.NoError(t, <-accepted)
}
