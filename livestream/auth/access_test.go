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
		name             string
		status           int
		body             string
		want             int
		wantRestrictions *PropertyRestrictions
	}{
		{name: "no content allows", status: http.StatusNoContent},
		{name: "empty restrictions allow", status: http.StatusOK, body: `{"restricted_event_properties": [], "restricted_person_properties": []}`},
		{
			name:   "restrictions are parsed",
			status: http.StatusOK,
			body:   `{"restricted_event_properties": ["$ip"], "restricted_person_properties": ["email"]}`,
			wantRestrictions: &PropertyRestrictions{
				EventProperties:  map[string]struct{}{"$ip": {}},
				PersonProperties: map[string]struct{}{"email": {}},
			},
		},
		{name: "malformed restrictions fail closed", status: http.StatusOK, body: `not json`, want: http.StatusServiceUnavailable},
		{name: "redirect fails closed", status: http.StatusFound, want: http.StatusServiceUnavailable},
		{name: "unauthorized denies", status: http.StatusUnauthorized, want: http.StatusUnauthorized},
		{name: "forbidden denies", status: http.StatusForbidden, want: http.StatusUnauthorized},
		{name: "server error fails closed", status: http.StatusInternalServerError, want: http.StatusServiceUnavailable},
	} {
		t.Run(test.name, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				assert.Equal(t, "Bearer test-live-stream-token", r.Header.Get("Authorization"))
				if r.URL.Path == "/redirected" {
					w.WriteHeader(http.StatusNoContent)
					return
				}
				w.Header().Set("Location", "/redirected")
				w.WriteHeader(test.status)
				_, _ = w.Write([]byte(test.body))
			}))
			defer server.Close()
			viper.Set("jwt.authorization_url", server.URL)
			t.Cleanup(func() { viper.Set("jwt.authorization_url", "") })
			restrictions, err := CheckAccess(context.Background(), http.Header{"Authorization": {"Bearer test-live-stream-token"}})
			if test.want == 0 {
				require.NoError(t, err)
				assert.Equal(t, test.wantRestrictions, restrictions)
			} else {
				var httpError *echo.HTTPError
				require.ErrorAs(t, err, &httpError)
				assert.Equal(t, test.want, httpError.Code)
				assert.Nil(t, restrictions)
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
	_, err := CheckAccess(context.Background(), http.Header{})
	require.ErrorAs(t, err, &httpError)
	assert.Equal(t, http.StatusServiceUnavailable, httpError.Code)
}

func TestCheckAccessBeforeRollout(t *testing.T) {
	viper.Set("jwt.authorization_url", "")
	restrictions, err := CheckAccess(context.Background(), http.Header{})
	require.NoError(t, err)
	assert.Nil(t, restrictions)
}
