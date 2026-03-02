package events

import (
	"context"
	"crypto/tls"
	"fmt"
	"time"

	"github.com/posthog/posthog/livestream/configs"
	"github.com/redis/go-redis/v9"
)

func newRedisClient(cfg configs.RedisConfig) (redis.UniversalClient, error) {
	if cfg.Address == "" {
		return nil, fmt.Errorf("redis: address not configured")
	}

	addr := fmt.Sprintf("%s:%s", cfg.Address, cfg.Port)

	var client redis.UniversalClient
	if cfg.TLS {
		client = redis.NewClusterClient(&redis.ClusterOptions{
			Addrs:     []string{addr},
			TLSConfig: &tls.Config{MinVersion: tls.VersionTLS12},
		})
	} else {
		client = redis.NewClient(&redis.Options{
			Addr: addr,
		})
	}

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	if err := client.Ping(ctx).Err(); err != nil {
		return nil, fmt.Errorf("redis ping failed: %w", err)
	}

	return client, nil
}
