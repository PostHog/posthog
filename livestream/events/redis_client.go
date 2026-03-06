package events

import (
	"context"
	"crypto/tls"
	"fmt"
	"time"

	"github.com/posthog/posthog/livestream/configs"
	"github.com/redis/rueidis"
)

func newRedisClient(cfg configs.RedisConfig) (rueidis.Client, error) {
	if cfg.Address == "" {
		return nil, fmt.Errorf("redis: address not configured")
	}

	addr := fmt.Sprintf("%s:%s", cfg.Address, cfg.Port)

	opts := rueidis.ClientOption{
		InitAddress:  []string{addr},
		DisableCache: true,
	}

	if cfg.TLS {
		opts.TLSConfig = &tls.Config{MinVersion: tls.VersionTLS12}
	}

	client, err := rueidis.NewClient(opts)
	if err != nil {
		return nil, fmt.Errorf("redis client create: %w", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	if err := client.Do(ctx, client.B().Ping().Build()).Error(); err != nil {
		client.Close()
		return nil, fmt.Errorf("redis ping failed: %w", err)
	}

	return client, nil
}
