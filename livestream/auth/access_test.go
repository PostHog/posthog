package auth

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
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
		isBehindProxy    bool
		trustAllProxies  bool
		trustedProxies   []string
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
		{name: "trusted proxy forwards allowed IP", status: http.StatusOK, body: `{"ip_restrictions":[["203.0.113.0/24"]]}`, remoteAddr: "10.0.0.2:8000", forwardedFor: "203.0.113.7", isBehindProxy: true, trustedProxies: []string{"10.0.0.2/32"}},
		{name: "forwarded spoof before actual client cannot allow", status: http.StatusOK, body: `{"ip_restrictions":[["203.0.113.0/24"]]}`, remoteAddr: "10.0.0.2:8000", forwardedFor: "203.0.113.7, 198.51.100.7", isBehindProxy: true, trustedProxies: []string{"10.0.0.2/32"}, want: http.StatusUnauthorized},
		{name: "private socket cannot forge forwarded IP", status: http.StatusOK, body: `{"ip_restrictions":[["203.0.113.0/24"]]}`, remoteAddr: "10.0.0.2:8000", forwardedFor: "203.0.113.7", want: http.StatusUnauthorized},
		{name: "loopback socket cannot forge forwarded IP", status: http.StatusOK, body: `{"ip_restrictions":[["203.0.113.0/24"]]}`, remoteAddr: "127.0.0.1:8000", forwardedFor: "203.0.113.7", want: http.StatusUnauthorized},
		{name: "link-local socket cannot forge forwarded IP", status: http.StatusOK, body: `{"ip_restrictions":[["203.0.113.0/24"]]}`, remoteAddr: "169.254.1.2:8000", forwardedFor: "203.0.113.7", want: http.StatusUnauthorized},
		{name: "private client in forwarded chain is not a proxy", status: http.StatusOK, body: `{"ip_restrictions":[["203.0.113.0/24"]]}`, remoteAddr: "10.0.0.2:8000", forwardedFor: "203.0.113.7, 10.1.2.3", isBehindProxy: true, trustedProxies: []string{"10.0.0.2/32"}, want: http.StatusUnauthorized},
		{name: "invalid proxy configuration fails closed", status: http.StatusOK, body: `{"ip_restrictions":[["203.0.113.0/24"]]}`, remoteAddr: "203.0.113.7:8000", isBehindProxy: true, trustedProxies: []string{"invalid"}, want: http.StatusServiceUnavailable},
		{name: "trust all proxies uses first forwarded IP", status: http.StatusOK, body: `{"ip_restrictions":[["203.0.113.0/24"]]}`, remoteAddr: "10.0.0.2:8000", forwardedFor: "203.0.113.7, 198.51.100.7", isBehindProxy: true, trustAllProxies: true},
		{name: "trust all proxies still denies blocked client", status: http.StatusOK, body: `{"ip_restrictions":[["203.0.113.0/24"]]}`, remoteAddr: "203.0.113.7:8000", forwardedFor: "198.51.100.7", isBehindProxy: true, trustAllProxies: true, want: http.StatusUnauthorized},
		{name: "trust all proxies requires behind proxy mode", status: http.StatusOK, body: `{"ip_restrictions":[["203.0.113.0/24"]]}`, remoteAddr: "198.51.100.7:8000", forwardedFor: "203.0.113.7", trustAllProxies: true, want: http.StatusUnauthorized},
		{name: "explicit proxies require behind proxy mode", status: http.StatusOK, body: `{"ip_restrictions":[["203.0.113.0/24"]]}`, remoteAddr: "10.0.0.2:8000", forwardedFor: "203.0.113.7", trustedProxies: []string{"10.0.0.2/32"}, want: http.StatusUnauthorized},
		{name: "behind proxy without trust rejects forwarded IP", status: http.StatusOK, body: `{"ip_restrictions":[["203.0.113.0/24"]]}`, remoteAddr: "10.0.0.2:8000", forwardedFor: "203.0.113.7", isBehindProxy: true, want: http.StatusUnauthorized},
		{name: "trust all proxies handles absent socket address", status: http.StatusOK, body: `{"ip_restrictions":[["203.0.113.0/24"]]}`, forwardedFor: "203.0.113.7", isBehindProxy: true, trustAllProxies: true},
		{name: "trust all proxies falls back to socket without header", status: http.StatusOK, body: `{"ip_restrictions":[["203.0.113.0/24"]]}`, remoteAddr: "203.0.113.7:8000", isBehindProxy: true, trustAllProxies: true},
		{name: "trust all proxies rejects malformed forwarded client", status: http.StatusOK, body: `{"ip_restrictions":[["203.0.113.0/24"]]}`, remoteAddr: "203.0.113.7:8000", forwardedFor: "invalid", isBehindProxy: true, trustAllProxies: true, want: http.StatusUnauthorized},
		{name: "trust all proxies accepts IPv6 with port", status: http.StatusOK, body: `{"ip_restrictions":[["2001:db8::7"]]}`, remoteAddr: "10.0.0.2:8000", forwardedFor: "[2001:db8::7]:443", isBehindProxy: true, trustAllProxies: true},
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
			viper.Set("trusted_proxies", test.trustedProxies)
			t.Cleanup(func() { viper.Set("trusted_proxies", nil) })
			viper.Set("is_behind_proxy", test.isBehindProxy)
			t.Cleanup(func() { viper.Set("is_behind_proxy", nil) })
			viper.Set("trust_all_proxies", test.trustAllProxies)
			t.Cleanup(func() { viper.Set("trust_all_proxies", nil) })
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

func TestCheckAccessAuthenticatesPolicyAccess(t *testing.T) {
	viewerKey := "test-viewer-token-signing-key-32-bytes"
	serviceKey := "test-service-policy-key-32-bytes-long"
	viper.Set("jwt.secret", viewerKey)
	viper.Set("jwt.authorization_signing_keys", serviceKey+",old-service-key")
	t.Cleanup(func() {
		viper.Set("jwt.authorization_signing_keys", nil)
		viper.Set("jwt.secret", nil)
		viper.Set("jwt.authorization_url", "")
	})
	viewerToken, err := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"aud": ExpectedScope, "exp": time.Now().Add(time.Minute).Unix(), "team_id": 7, "api_token": "test-project-token",
	}).SignedString([]byte(viewerKey))
	require.NoError(t, err)
	authorization := "Bearer " + viewerToken
	viewerHash := sha256.Sum256([]byte(authorization))
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		token, err := jwt.Parse(r.Header.Get("X-PostHog-Livestream-Service-Token"), func(token *jwt.Token) (interface{}, error) {
			return []byte(serviceKey), nil
		}, jwt.WithAudience("posthog:livestream:authorization"), jwt.WithValidMethods([]string{"HS256"}), jwt.WithExpirationRequired())
		if !assert.NoError(t, err) {
			w.WriteHeader(http.StatusForbidden)
			return
		}
		claims := token.Claims.(jwt.MapClaims)
		assert.Equal(t, float64(7), claims["team_id"])
		assert.Equal(t, "read_ip_policy", claims["operation"])
		assert.Equal(t, hex.EncodeToString(viewerHash[:]), claims["viewer_token_sha256"])
		_, _ = w.Write([]byte(`{"ip_restrictions":[["203.0.113.0/24"]]}`))
	}))
	defer server.Close()
	viper.Set("jwt.authorization_url", server.URL)
	request := httptest.NewRequest(http.MethodGet, "/events", nil)
	request.RemoteAddr = "203.0.113.7:8000"
	request.Header.Set("Authorization", authorization)
	request.Header.Set("X-PostHog-Livestream-Service-Token", "caller-supplied-proof")
	_, err = CheckAccess(context.Background(), request)
	require.NoError(t, err)
}
