package auth

import (
	"github.com/stretchr/testify/assert"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/spf13/viper"
)

func TestDecodeAuthToken(t *testing.T) {
	// Set up a mock secret for testing
	viper.Set("jwt.secret", "test-secret")

	tests := []struct {
		name           string
		authHeader     string
		expectError    bool
		expectedAud    string
		expectedTeamID int
		expectedToken  string
	}{
		{
			name: "Valid token",
			authHeader: "Bearer " + createValidToken(ExpectedScope, jwt.MapClaims{
				"team_id":   123.,
				"api_token": "token123",
			}),
			expectError:    false,
			expectedAud:    ExpectedScope,
			expectedTeamID: 123,
			expectedToken:  "token123",
		},
		{
			name:        "Invalid token format",
			authHeader:  "InvalidToken",
			expectError: true,
		},
		{
			name:        "Missing Bearer prefix",
			authHeader:  createValidToken(ExpectedScope, nil),
			expectError: true,
		},
		{
			name:        "Invalid audience",
			authHeader:  "Bearer " + createValidToken("invalid:scope", nil),
			expectError: true,
		},
		{
			name:        "Expired token",
			authHeader:  "Bearer " + createExpiredToken(),
			expectError: true,
		},
		{
			name:        "Invalid signature",
			authHeader:  "Bearer " + createTokenWithInvalidSignature(),
			expectError: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			claims, err := decodeAuthToken(tt.authHeader)

			if tt.expectError {
				if err == nil {
					t.Errorf("Expected an error, but got nil")
				}
			} else {
				if err != nil {
					t.Errorf("Unexpected error: %v", err)
				}
				if claims["aud"] != tt.expectedAud {
					t.Errorf("Expected audience %s, but got %s", tt.expectedAud, claims["aud"])
				}
				teamID, token, err := getDataFromClaims(claims)
				if err != nil {
					t.Errorf("Unexpected error: %v", err)
				}
				assert.Equal(t, tt.expectedTeamID, teamID)
				assert.Equal(t, tt.expectedToken, token)
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
