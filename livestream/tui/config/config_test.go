package config

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

func TestCredentials_IsExpired(t *testing.T) {
	tests := []struct {
		name      string
		expiresAt time.Time
		expected  bool
	}{
		{"not expired", time.Now().Add(time.Hour), false},
		{"expired", time.Now().Add(-time.Hour), true},
		{"just expired", time.Now().Add(-time.Second), true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			creds := &Credentials{ExpiresAt: tt.expiresAt}
			assert.Equal(t, tt.expected, creds.IsExpired())
		})
	}
}
