package auth

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/labstack/echo/v4"
	"github.com/spf13/viper"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestCheckAccess(t *testing.T) {
	for _, test := range []struct {
		status int
		want   int
	}{
		{http.StatusNoContent, 0},
		{http.StatusOK, http.StatusServiceUnavailable},
		{http.StatusFound, http.StatusServiceUnavailable},
		{http.StatusUnauthorized, http.StatusUnauthorized},
		{http.StatusForbidden, http.StatusUnauthorized},
		{http.StatusInternalServerError, http.StatusServiceUnavailable},
	} {
		t.Run(http.StatusText(test.status), func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				assert.Equal(t, "Bearer test-live-stream-token", r.Header.Get("Authorization"))
				if r.URL.Path == "/redirected" {
					w.WriteHeader(http.StatusNoContent)
					return
				}
				w.Header().Set("Location", "/redirected")
				w.WriteHeader(test.status)
			}))
			defer server.Close()
			viper.Set("jwt.authorization_url", server.URL)
			t.Cleanup(func() { viper.Set("jwt.authorization_url", "") })
			err := CheckAccess(context.Background(), http.Header{"Authorization": {"Bearer test-live-stream-token"}})
			if test.want == 0 {
				require.NoError(t, err)
			} else {
				var httpError *echo.HTTPError
				require.ErrorAs(t, err, &httpError)
				assert.Equal(t, test.want, httpError.Code)
			}
		})
	}
}

func TestCheckAccessFailsClosedOnConnectionFailure(t *testing.T) {
	server := httptest.NewServer(http.NotFoundHandler())
	server.Close()
	viper.Set("jwt.authorization_url", server.URL)
	t.Cleanup(func() { viper.Set("jwt.authorization_url", "") })
	var httpError *echo.HTTPError
	require.ErrorAs(t, CheckAccess(context.Background(), http.Header{}), &httpError)
	assert.Equal(t, http.StatusServiceUnavailable, httpError.Code)
}

func TestCheckAccessBeforeRollout(t *testing.T) {
	viper.Set("jwt.authorization_url", "")
	require.NoError(t, CheckAccess(context.Background(), http.Header{}))
}
