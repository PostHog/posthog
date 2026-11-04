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
		remoteAddr       string
		forwardedFor     string
		wantRestrictions *PropertyRestrictions
	}{
		{name: "no content allows", status: http.StatusNoContent},
		{name: "empty restrictions allow", status: http.StatusOK, body: `{"restricted_event_properties": [], "restricted_person_properties": []}`},
		{
			name:   "restrictions are parsed",
			status: http.StatusOK,
			body:   `{"restricted_event_properties": ["$ip"], "restricted_person_properties": ["email"], "restricted_group_properties": {"organization": ["email"], "project": []}}`,
			wantRestrictions: &PropertyRestrictions{
				EventProperties:  map[string]struct{}{"$ip": {}},
				PersonProperties: map[string]struct{}{"email": {}},
				GroupProperties:  map[string]map[string]struct{}{"organization": {"email": {}}},
			},
		},
		{name: "allowed IP", status: http.StatusOK, body: `{"ip_restrictions":[["203.0.113.0/24"]]}`, remoteAddr: "203.0.113.7:8000"},
		{name: "denied IP", status: http.StatusOK, body: `{"ip_restrictions":[["203.0.113.0/24"]]}`, remoteAddr: "198.51.100.7:8000", want: http.StatusUnauthorized},
		{name: "every organization must allow", status: http.StatusOK, body: `{"ip_restrictions":[["203.0.113.0/24"],["198.51.100.7"]]}`, remoteAddr: "203.0.113.7:8000", want: http.StatusUnauthorized},
		{name: "IPv6 address", status: http.StatusOK, body: `{"ip_restrictions":[["2001:db8::7"]]}`, remoteAddr: "[2001:db8::7]:8000"},
		{name: "missing IP denies", status: http.StatusOK, body: `{"ip_restrictions":[["203.0.113.0/24"]]}`, want: http.StatusUnauthorized},
		{name: "untrusted forwarded IP cannot allow", status: http.StatusOK, body: `{"ip_restrictions":[["203.0.113.0/24"]]}`, remoteAddr: "198.51.100.7:8000", forwardedFor: "203.0.113.7", want: http.StatusUnauthorized},
		{name: "trusted proxy forwards allowed IP", status: http.StatusOK, body: `{"ip_restrictions":[["203.0.113.0/24"]]}`, remoteAddr: "10.0.0.2:8000", forwardedFor: "203.0.113.7"},
		{name: "forwarded spoof before actual client cannot allow", status: http.StatusOK, body: `{"ip_restrictions":[["203.0.113.0/24"]]}`, remoteAddr: "10.0.0.2:8000", forwardedFor: "203.0.113.7, 198.51.100.7", want: http.StatusUnauthorized},
		{name: "invalid policy fails closed", status: http.StatusOK, body: `{"ip_restrictions":[["invalid"]]}`, remoteAddr: "203.0.113.7:8000", want: http.StatusServiceUnavailable},
		{name: "malformed restrictions fail closed", status: http.StatusOK, body: `not json`, want: http.StatusServiceUnavailable},
		{name: "redirect fails closed", status: http.StatusFound, want: http.StatusServiceUnavailable},
		{name: "unauthorized denies", status: http.StatusUnauthorized, want: http.StatusUnauthorized},
		{name: "forbidden denies", status: http.StatusForbidden, want: http.StatusUnauthorized},
		{name: "server error fails closed", status: http.StatusInternalServerError, want: http.StatusServiceUnavailable},
	} {
		t.Run(test.name, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				assert.Equal(t, "Bearer test-live-stream-token", r.Header.Get("Authorization"))
				assert.Equal(t, "application/json", r.Header.Get("Accept"))
				assert.Equal(t, "1", r.Header.Get("X-PostHog-Livestream-IP-Policy"))
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
			viewer := httptest.NewRequest(http.MethodGet, "/events", nil)
			viewer.RemoteAddr = test.remoteAddr
			viewer.Header.Set("Authorization", "Bearer test-live-stream-token")
			viewer.Header.Set("X-Forwarded-For", test.forwardedFor)
			restrictions, err := CheckAccess(context.Background(), viewer)
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
	_, err := CheckAccess(context.Background(), &http.Request{Header: http.Header{}})
	require.ErrorAs(t, err, &httpError)
	assert.Equal(t, http.StatusServiceUnavailable, httpError.Code)
}

func TestCheckAccessBeforeRollout(t *testing.T) {
	viper.Set("jwt.authorization_url", "")
	restrictions, err := CheckAccess(context.Background(), &http.Request{Header: http.Header{}})
	require.NoError(t, err)
	assert.Nil(t, restrictions)
}

func TestRestrictsGeo(t *testing.T) {
	for key, want := range map[string]bool{"$ip": true, "$geoip_city_name": true, "$browser": false} {
		restrictions := &PropertyRestrictions{EventProperties: map[string]struct{}{key: {}}}
		assert.Equal(t, want, restrictions.RestrictsGeo(), key)
	}
	var none *PropertyRestrictions
	assert.False(t, none.RestrictsGeo())
}

func TestRestrictsGroupPropertyForAnyType(t *testing.T) {
	restrictions := &PropertyRestrictions{GroupProperties: map[string]map[string]struct{}{
		AnyGroupType:   {"email": {}},
		"organization": {"plan": {}},
	}}
	assert.True(t, restrictions.RestrictsGroupProperty("organization", "email"))
	assert.True(t, restrictions.RestrictsGroupProperty("project", "email"))
	assert.True(t, restrictions.RestrictsGroupProperty("organization", "plan"))
	assert.False(t, restrictions.RestrictsGroupProperty("project", "plan"))
}
