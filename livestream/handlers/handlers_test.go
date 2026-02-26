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
	"github.com/redis/go-redis/v9"
	"github.com/spf13/viper"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestStreamEventsHandler_AuthValidation(t *testing.T) {
	logger := echo.New().Logger
	subChan := make(chan events.Subscription, 10)
	filter := &events.Filter{
		UnSubChan: make(chan events.Subscription, 10),
	}
	handler := StreamEventsHandler(logger, subChan, filter)

	tests := []struct {
		name           string
		setupHeader    func(*http.Request)
		expectedStatus int
		expectedError  string
		description    string
	}{
		{
			name: "Missing authorization header returns unauthorized",
			setupHeader: func(req *http.Request) {
			},
			expectedStatus: http.StatusUnauthorized,
			expectedError:  "wrong token",
			description:    "When auth header is missing, GetAuthClaims returns error and handler should return 401",
		},
		{
			name: "Invalid auth header returns unauthorized",
			setupHeader: func(req *http.Request) {
				req.Header.Set("Authorization", "InvalidToken")
			},
			expectedStatus: http.StatusUnauthorized,
			expectedError:  "wrong token",
			description:    "When auth header is invalid, GetAuthClaims returns error and handler should return 401",
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
	filter := &events.Filter{
		UnSubChan: make(chan events.Subscription, 10),
	}
	handler := StreamEventsHandler(logger, subChan, filter)

	tests := []struct {
		name         string
		claims       jwt.MapClaims
		expectError  bool
		errorMessage string
		description  string
	}{
		{
			name: "Empty api_token should return unauthorized",
			claims: jwt.MapClaims{
				"team_id":   123,
				"api_token": "",
			},
			expectError:  true,
			errorMessage: "wrong token",
			description:  "New validation: empty token should be rejected even with valid JWT",
		},
		{
			name: "Team ID 0 should return unauthorized",
			claims: jwt.MapClaims{
				"team_id":   0,
				"api_token": "valid-token",
			},
			expectError:  true,
			errorMessage: "wrong token",
			description:  "New validation: teamID=0 should be rejected even with valid JWT",
		},
		{
			name: "HappyPath",
			claims: jwt.MapClaims{
				"team_id":   7,
				"api_token": "valid-token",
			},
			expectError: false,
			description: "New validation: teamID=7 should be accepted even with valid JWT",
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
	client := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	t.Cleanup(func() { _ = client.Close() })
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

	err := handler(c)
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
