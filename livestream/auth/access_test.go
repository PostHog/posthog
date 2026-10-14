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
			body:   `{"restricted_event_properties": ["$ip"], "restricted_person_properties": ["email"], "restricted_group_properties": {"organization": ["email"], "project": []}}`,
			wantRestrictions: &PropertyRestrictions{
				EventProperties:  map[string]struct{}{"$ip": {}},
				PersonProperties: map[string]struct{}{"email": {}},
				GroupProperties:  map[string]map[string]struct{}{"organization": {"email": {}}},
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
				assert.Equal(t, "application/json", r.Header.Get("Accept"))
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
