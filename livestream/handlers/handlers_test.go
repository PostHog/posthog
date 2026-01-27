package handlers

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/labstack/echo/v4"
	"github.com/posthog/posthog/livestream/auth"
	"github.com/posthog/posthog/livestream/events"
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
