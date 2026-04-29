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
