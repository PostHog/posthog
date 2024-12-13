package main

import (
	"testing"
	"time"

	"github.com/golang-jwt/jwt"
	"github.com/spf13/viper"
)

func TestDecodeAuthToken(t *testing.T) {
	// Set up a mock secret for testing
	viper.Set("jwt.secret", "test-secret")

	tests := []struct {
		name        string
		authHeader  string
		expectError bool
		expectedAud string
	}{
		{
			name:        "Valid token",
			authHeader:  "Bearer " + createValidToken(ExpectedScope),
			expectError: false,
			expectedAud: ExpectedScope,
		},
		{
			name:        "Invalid token format",
			authHeader:  "InvalidToken",
			expectError: true,
		},
		{
			name:        "Missing Bearer prefix",
			authHeader:  createValidToken(ExpectedScope),
			expectError: true,
		},
		{
			name:        "Invalid audience",
			authHeader:  "Bearer " + createValidToken("invalid:scope"),
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
			}
		})
	}
}

func createValidToken(audience string) string {
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"aud": audience,
		"exp": time.Now().Add(time.Hour).Unix(),
	})
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
