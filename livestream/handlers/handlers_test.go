package handlers

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/golang-jwt/jwt/v5"
	"github.com/labstack/echo/v4"
	"github.com/posthog/posthog/livestream/auth"
	"github.com/posthog/posthog/livestream/events"
	"github.com/redis/rueidis"
	"github.com/spf13/viper"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestStreamEventsHandler_AuthValidation(t *testing.T) {
	logger := echo.New().Logger
	subChan := make(chan events.Subscription, 10)
	unSubChan := make(chan events.Subscription, 10)
	handler := StreamEventsHandler(logger, subChan, unSubChan)

	tests := []struct {
		name           string
		description    string
		setupHeader    func(*http.Request)
		expectedStatus int
		expectedError  string
	}{
		{
			name:        "Missing authorization header returns unauthorized",
			description: "When auth header is missing, handler should return 401 with 'wrong token'",
			setupHeader: func(req *http.Request) {
			},
			expectedStatus: http.StatusUnauthorized,
			expectedError:  "wrong token",
		},
		{
			name:        "Invalid auth header returns unauthorized",
			description: "When auth header is invalid (not Bearer format), handler should return 401 with 'wrong token'",
			setupHeader: func(req *http.Request) {
				req.Header.Set("Authorization", "InvalidToken")
			},
			expectedStatus: http.StatusUnauthorized,
			expectedError:  "wrong token",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			e := echo.New()
			req := httptest.NewRequest(http.MethodGet, "/events", nil)
			ctx, canc := context.WithTimeout(context.Background(), time.Millisecond)
			defer canc()
			req = req.WithContext(ctx)
			tt.setupHeader(req)
			rec := httptest.NewRecorder()
			c := e.NewContext(req, rec)

			err := handler(c)

			require.Error(t, err, tt.description)
			httpErr, ok := err.(*echo.HTTPError)
			require.True(t, ok, "error should be an HTTPError")
			assert.Equal(t, tt.expectedStatus, httpErr.Code)
			assert.Equal(t, tt.expectedError, httpErr.Message)
		})
	}
}

func TestStreamEventsHandler_TokenAndTeamIDValidation(t *testing.T) {
	viper.Set("jwt.secret", "test-secret-for-handlers")

	logger := echo.New().Logger
	subChan := make(chan events.Subscription, 10)
	unSubChan := make(chan events.Subscription, 10)
	handler := StreamEventsHandler(logger, subChan, unSubChan)

	tests := []struct {
		name         string
		description  string
		claims       jwt.MapClaims
		expectError  bool
		errorMessage string
	}{
		{
			name:        "Empty api_token should return unauthorized",
			description: "New validation: empty token in JWT claims should be rejected with 401",
			claims: jwt.MapClaims{
				"team_id":   123,
				"api_token": "",
			},
			expectError:  true,
			errorMessage: "wrong token",
		},
		{
			name:        "Team ID 0 should return unauthorized",
			description: "New validation: teamID=0 in JWT claims should be rejected with 401",
			claims: jwt.MapClaims{
				"team_id":   0,
				"api_token": "valid-token",
			},
			expectError:  true,
			errorMessage: "wrong token",
		},
		{
			name:        "Valid token and team ID succeeds",
			description: "New validation: teamID=7 and non-empty token should pass validation",
			claims: jwt.MapClaims{
				"team_id":   7,
				"api_token": "valid-token",
			},
			expectError: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			token := createJWTToken(auth.ExpectedScope, tt.claims)

			e := echo.New()
			req := httptest.NewRequest(http.MethodGet, "/events", nil)
			req.Header.Set("Authorization", "Bearer "+token)
			ctx, canc := context.WithTimeout(context.Background(), time.Millisecond)
			defer canc()
			req = req.WithContext(ctx)
			rec := httptest.NewRecorder()
			c := e.NewContext(req, rec)

			err := handler(c)

			if tt.expectError {
				require.Error(t, err, tt.description)
				httpErr, ok := err.(*echo.HTTPError)
				require.True(t, ok, "error should be an HTTPError")
				assert.Equal(t, http.StatusUnauthorized, httpErr.Code)
				assert.Equal(t, tt.errorMessage, httpErr.Message)
			} else {
				assert.NoError(t, err, tt.description)
			}
		})
	}
}

func createJWTToken(audience string, claims jwt.MapClaims) string {
	newClaims := jwt.MapClaims{
		"aud": audience,
		"exp": time.Now().Add(time.Hour).Unix(),
	}
	for k, v := range claims {
		newClaims[k] = v
	}
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, newClaims)
	tokenString, _ := token.SignedString([]byte(viper.GetString("jwt.secret")))
	return tokenString
}

func TestStatsHandler_ReadsFromRedis(t *testing.T) {
	viper.Set("jwt.secret", "test-secret-for-stats")
	apiToken := "phx_test_token"

	mr := miniredis.RunT(t)
	client, err := rueidis.NewClient(rueidis.ClientOption{
		InitAddress:  []string{mr.Addr()},
		DisableCache: true,
	})
	require.NoError(t, err)
	t.Cleanup(func() { client.Close() })
	rw := events.NewStatsInRedisFromClient(client)

	ctx := context.Background()
	require.NoError(t, rw.AddUser(ctx, apiToken, "user1"))
	require.NoError(t, rw.AddUser(ctx, apiToken, "user2"))
	require.NoError(t, rw.AddSession(ctx, apiToken, "sess1"))

	stats := events.NewStatsKeeper()
	sessionStats := events.NewSessionStatsKeeper(0, 0)

	handler := StatsHandler(stats, sessionStats, rw)

	token := createJWTToken(auth.ExpectedScope, jwt.MapClaims{
		"team_id":   1,
		"api_token": apiToken,
	})

	e := echo.New()
	req := httptest.NewRequest(http.MethodGet, "/stats", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	c := e.NewContext(req, rec)

	err = handler(c)
	require.NoError(t, err)
	assert.Equal(t, http.StatusOK, rec.Code)

	var resp struct {
		UsersOnProduct   int    `json:"users_on_product"`
		ActiveRecordings int    `json:"active_recordings"`
		Error            string `json:"error"`
	}
	require.NoError(t, json.Unmarshal(rec.Body.Bytes(), &resp))
	assert.Equal(t, 2, resp.UsersOnProduct)
	assert.Equal(t, 1, resp.ActiveRecordings)
	assert.Empty(t, resp.Error)
}

func TestStatsHandler_FallsBackToLocal(t *testing.T) {
	viper.Set("jwt.secret", "test-secret-for-stats")
	apiToken := "phx_test_token"

	stats := events.NewStatsKeeper()
	stats.GetStoreForToken(apiToken).Add("user1", events.NoSpaceType{})
	stats.GetStoreForToken(apiToken).Add("user2", events.NoSpaceType{})
	stats.GetStoreForToken(apiToken).Add("user3", events.NoSpaceType{})

	sessionStats := events.NewSessionStatsKeeper(0, 0)
	sessionStats.Add(apiToken, "sess1")
	sessionStats.Add(apiToken, "sess2")

	handler := StatsHandler(stats, sessionStats, nil)

	token := createJWTToken(auth.ExpectedScope, jwt.MapClaims{
		"team_id":   1,
		"api_token": apiToken,
	})

	e := echo.New()
	req := httptest.NewRequest(http.MethodGet, "/stats", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	c := e.NewContext(req, rec)

	err := handler(c)
	require.NoError(t, err)
	assert.Equal(t, http.StatusOK, rec.Code)

	var resp struct {
		UsersOnProduct   int    `json:"users_on_product"`
		ActiveRecordings int    `json:"active_recordings"`
		Error            string `json:"error"`
	}
	require.NoError(t, json.Unmarshal(rec.Body.Bytes(), &resp))
	assert.Equal(t, 3, resp.UsersOnProduct)
	assert.Equal(t, 2, resp.ActiveRecordings)
	assert.Empty(t, resp.Error)
}

func TestFilterNotificationForUser(t *testing.T) {
	const userID = 42

	tests := []struct {
		name       string
		payload    string
		wantOK     bool
		wantReason string
		wantHasKey string // a key expected to be present in cleaned output when delivered
	}{
		{
			name:       "invalid json -> malformed_payload",
			payload:    "not-json",
			wantOK:     false,
			wantReason: "malformed_payload",
		},
		{
			name:       "missing resolved_user_ids -> malformed_payload",
			payload:    `{"id": "n1"}`,
			wantOK:     false,
			wantReason: "malformed_payload",
		},
		{
			name:       "resolved_user_ids wrong type -> malformed_payload",
			payload:    `{"id": "n1", "resolved_user_ids": "42"}`,
			wantOK:     false,
			wantReason: "malformed_payload",
		},
		{
			name:       "user not in list -> wrong_user",
			payload:    `{"id": "n1", "resolved_user_ids": [1, 2, 3]}`,
			wantOK:     false,
			wantReason: "wrong_user",
		},
		{
			name:       "user in list -> delivered, resolved_user_ids stripped",
			payload:    `{"id": "n1", "resolved_user_ids": [1, 42, 3], "body": "hi"}`,
			wantOK:     true,
			wantHasKey: "body",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cleaned, ok, reason := filterNotificationForUser(tt.payload, userID)
			assert.Equal(t, tt.wantOK, ok)
			assert.Equal(t, tt.wantReason, reason)
			if ok {
				var out map[string]interface{}
				require.NoError(t, json.Unmarshal([]byte(cleaned), &out))
				_, present := out["resolved_user_ids"]
				assert.False(t, present, "resolved_user_ids must be stripped from delivered payload")
				if tt.wantHasKey != "" {
					_, present := out[tt.wantHasKey]
					assert.True(t, present, "expected key %q in cleaned payload", tt.wantHasKey)
				}
			} else {
				assert.Empty(t, cleaned)
			}
		})
	}
}

func TestParsePropertyFilters(t *testing.T) {
	tests := []struct {
		name string
		raw  []string
		want map[string][]string
	}{
		{
			name: "nil input",
			raw:  nil,
			want: nil,
		},
		{
			name: "empty input",
			raw:  []string{},
			want: nil,
		},
		{
			name: "single key=value",
			raw:  []string{"$browser=Chrome"},
			want: map[string][]string{"$browser": {"Chrome"}},
		},
		{
			name: "multiple keys AND",
			raw:  []string{"$browser=Chrome", "plan=enterprise"},
			want: map[string][]string{
				"$browser": {"Chrome"},
				"plan":     {"enterprise"},
			},
		},
		{
			name: "same key OR",
			raw:  []string{"$browser=Chrome", "$browser=Firefox"},
			want: map[string][]string{"$browser": {"Chrome", "Firefox"}},
		},
		{
			name: "missing equals skipped",
			raw:  []string{"$browser", "plan=free"},
			want: map[string][]string{"plan": {"free"}},
		},
		{
			name: "empty key skipped",
			raw:  []string{"=Chrome", "plan=free"},
			want: map[string][]string{"plan": {"free"}},
		},
		{
			name: "all malformed returns nil",
			raw:  []string{"=foo", "bar"},
			want: nil,
		},
		{
			name: "empty value allowed",
			raw:  []string{"plan="},
			want: map[string][]string{"plan": {""}},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := parsePropertyFilters(tt.raw)
			assert.Equal(t, tt.want, got)
		})
	}
}
