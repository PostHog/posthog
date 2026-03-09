//go:build integration

package events

import (
	"testing"

	"github.com/posthog/posthog/livestream/configs"
	"github.com/redis/rueidis"
)

func NewIntegrationTestClient(t *testing.T) rueidis.Client {
	t.Helper()
	cfg := configs.RedisConfig{Address: "127.0.0.1", Port: "7001"}
	client, err := newRedisClient(cfg)
	if err != nil {
		t.Fatalf("cannot create Redis cluster client: %v", err)
	}

	t.Cleanup(func() { client.Close() })
	return client
}
