package auth

import (
	"net/http"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/spf13/viper"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestDecodeAuthToken(t *testing.T) {
	viper.Set("jwt.secret", "test-secret")

	tests := []struct {
		name        string
		authHeader  string
		expectError bool
		expectedAud string
	}{
		{
			name: "Valid token",
			authHeader: "Bearer " + createValidToken(ExpectedScope, jwt.MapClaims{
				"team_id": 123., "api_token": "token123", "user_id": 1., "organization_id": "org-1",
			}),
			expectedAud: ExpectedScope,
		},
		{name: "Invalid token format", authHeader: "InvalidToken", expectError: true},
		{name: "Missing Bearer prefix", authHeader: createValidToken(ExpectedScope, nil), expectError: true},
		{name: "Invalid audience", authHeader: "Bearer " + createValidToken("invalid:scope", nil), expectError: true},
		{name: "Expired token", authHeader: "Bearer " + createExpiredToken(), expectError: true},
		{name: "Invalid signature", authHeader: "Bearer " + createTokenWithInvalidSignature(), expectError: true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			claims, err := decodeAuthToken(tt.authHeader)
			if tt.expectError {
				assert.Error(t, err)
			} else {
				require.NoError(t, err)
				assert.Equal(t, tt.expectedAud, claims["aud"])
			}
		})
	}
}

func TestParseAuthClaims(t *testing.T) {
	viper.Set("jwt.secret", "test-secret")

	tests := []struct {
		name           string
		claims         jwt.MapClaims
		expectError    string
		expectedTeamID int
		expectedUserID int
		expectedOrgID  string
		expectedToken  string
	}{
		{
			name:           "Valid token with all claims",
			claims:         jwt.MapClaims{"team_id": 123., "api_token": "token123", "user_id": 42., "organization_id": "org-uuid-123"},
			expectedTeamID: 123, expectedUserID: 42, expectedOrgID: "org-uuid-123", expectedToken: "token123",
		},
		{
			name:           "Backward compat: user_id and organization_id optional",
			claims:         jwt.MapClaims{"team_id": 123., "api_token": "token123"},
			expectedTeamID: 123, expectedToken: "token123",
		},
		{
			name:        "Missing team_id",
			claims:      jwt.MapClaims{"api_token": "token123", "user_id": 42., "organization_id": "org-1"},
			expectError: "invalid team_id",
		},
		{
			name:        "Missing api_token",
			claims:      jwt.MapClaims{"team_id": 123., "user_id": 42., "organization_id": "org-1"},
			expectError: "invalid api_token",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			token := createValidToken(ExpectedScope, tt.claims)
			header := http.Header{"Authorization": {"Bearer " + token}}

			parsed, err := ParseAuthClaims(header)
			if tt.expectError != "" {
				assert.ErrorContains(t, err, tt.expectError)
			} else {
				require.NoError(t, err)
				assert.Equal(t, tt.expectedTeamID, parsed.TeamID)
				assert.Equal(t, tt.expectedUserID, parsed.UserID)
				assert.Equal(t, tt.expectedOrgID, parsed.OrganizationID)
				assert.Equal(t, tt.expectedToken, parsed.Token)
			}
		})
	}
}

func TestDecodeAuthTokenWithFallbackSecrets(t *testing.T) {
	viper.Set("jwt.secret", "current-secret")
	t.Cleanup(func() {
		viper.Set("jwt.secret", "test-secret")
		viper.Set("jwt.secret_fallbacks", nil)
	})

	tests := []struct {
		name        string
		fallbacks   any
		signingKey  string
		expectError bool
	}{
		{name: "current secret with no fallbacks", fallbacks: nil, signingKey: "current-secret"},
		{name: "old secret with no fallbacks", fallbacks: nil, signingKey: "old-secret-1", expectError: true},
		{name: "current secret with fallbacks set", fallbacks: "old-secret-1,old-secret-2", signingKey: "current-secret"},
		{name: "first fallback, env-style comma string", fallbacks: "old-secret-1,old-secret-2", signingKey: "old-secret-1"},
		{name: "second fallback, env-style comma string", fallbacks: "old-secret-1,old-secret-2", signingKey: "old-secret-2"},
		{name: "fallback from yaml-style list", fallbacks: []string{"old-secret-1", "old-secret-2"}, signingKey: "old-secret-2"},
		{name: "whitespace around commas is trimmed", fallbacks: "old-secret-1, old-secret-2", signingKey: "old-secret-2"},
		{name: "unknown secret with fallbacks set", fallbacks: "old-secret-1,old-secret-2", signingKey: "wrong-secret", expectError: true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			viper.Set("jwt.secret_fallbacks", tt.fallbacks)

			claims, err := decodeAuthToken("Bearer " + createTokenSignedWith(tt.signingKey))
			if tt.expectError {
				assert.ErrorContains(t, err, "signature is invalid")
			} else {
				require.NoError(t, err)
				assert.Equal(t, ExpectedScope, claims["aud"])
			}
		})
	}
}

func createTokenSignedWith(secret string) string {
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"aud": ExpectedScope,
		"exp": time.Now().Add(time.Hour).Unix(),
	})
	tokenString, _ := token.SignedString([]byte(secret))
	return tokenString
}

func createValidToken(audience string, claims jwt.MapClaims) string {
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

func createExpiredToken() string {
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"aud": ExpectedScope,
		"exp": time.Now().Add(-time.Hour).Unix(),
	})
	tokenString, _ := token.SignedString([]byte(viper.GetString("jwt.secret")))
	return tokenString
}

func createTokenWithInvalidSignature() string {
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"aud": ExpectedScope,
		"exp": time.Now().Add(time.Hour).Unix(),
	})
	tokenString, _ := token.SignedString([]byte("wrong-secret"))
	return tokenString
}
