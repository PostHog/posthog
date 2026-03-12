package auth

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestDeriveStreamHost(t *testing.T) {
	tests := []struct {
		name     string
		appHost  string
		expected string
	}{
		{"US cloud", "https://us.posthog.com", "https://live.us.posthog.com"},
		{"US cloud trailing slash", "https://us.posthog.com/", "https://live.us.posthog.com"},
		{"app.posthog.com defaults to US", "https://app.posthog.com", "https://live.us.posthog.com"},
		{"EU cloud", "https://eu.posthog.com", "https://live.eu.posthog.com"},
		{"dev environment", "https://app.dev.posthog.dev", "https://live.dev.posthog.dev"},
		{"local dev", "http://localhost:8000", "http://localhost:8010"},
		{"unknown host", "https://custom.example.com", "http://localhost:8010"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := DeriveStreamHost(tt.appHost)
			assert.Equal(t, tt.expected, result)
		})
	}
}
