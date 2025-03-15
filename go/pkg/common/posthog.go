package common

import (
	"fmt"
	"os"
)

// PostHogConfig holds common configuration for PostHog services
type PostHogConfig struct {
	Host       string
	ProjectID  string
	APIKey     string
	InstanceID string
}

// NewPostHogConfig creates a new PostHog configuration from environment variables
func NewPostHogConfig() (*PostHogConfig, error) {
	host := os.Getenv("POSTHOG_HOST")
	if host == "" {
		host = "https://app.posthog.com"
	}

	projectID := os.Getenv("POSTHOG_PROJECT_ID")
	if projectID == "" {
		return nil, fmt.Errorf("POSTHOG_PROJECT_ID environment variable is required")
	}

	apiKey := os.Getenv("POSTHOG_API_KEY")
	if apiKey == "" {
		return nil, fmt.Errorf("POSTHOG_API_KEY environment variable is required")
	}

	instanceID := os.Getenv("INSTANCE_ID")
	if instanceID == "" {
		return nil, fmt.Errorf("INSTANCE_ID environment variable is required")
	}

	return &PostHogConfig{
		Host:       host,
		ProjectID:  projectID,
		APIKey:     apiKey,
		InstanceID: instanceID,
	}, nil
}
