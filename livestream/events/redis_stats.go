package events

import (
	"context"
	"crypto/tls"
	"fmt"
	"time"

	"github.com/posthog/posthog/livestream/configs"
	"github.com/posthog/posthog/livestream/metrics"
	"github.com/redis/go-redis/v9"
)

const (
	userKeyTTL    = 60 * time.Second
	sessionKeyTTL = 5 * time.Minute
)

type RedisStatsWriter struct {
	client  redis.Cmdable

	// Needed for testing.
	// By default, nowFunc will be nil and RedisStatsWriter will use Redis' Time so all workers use the same clock
	// When testing, this can be set to a fake clock to allow time manipulation
	nowFunc func(ctx context.Context) (time.Time, error)
}

func (w *RedisStatsWriter) now(ctx context.Context) (time.Time, error) {
	if w.nowFunc != nil {
		return w.nowFunc(ctx)
	}
	return w.client.Time(ctx).Result()
}

func NewRedisStatsWriter(cfg configs.RedisConfig) (*RedisStatsWriter, error) {
	if cfg.Address == "" {
		return nil, fmt.Errorf("redis: address not configured")
	}

	addr := fmt.Sprintf("%s:%s", cfg.Address, cfg.Port)

	var client redis.Cmdable
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

	var pingErr error
	switch c := client.(type) {
	case *redis.Client:
		pingErr = c.Ping(ctx).Err()
	case *redis.ClusterClient:
		pingErr = c.Ping(ctx).Err()
	}
	if pingErr != nil {
		return nil, fmt.Errorf("redis ping failed: %w", pingErr)
	}

	return &RedisStatsWriter{client: client}, nil
}

func userKey(token string) string {
	return fmt.Sprintf("livestream:users:%s", token)
}

func sessionKey(token string) string {
	return fmt.Sprintf("livestream:sessions:%s", token)
}

func (w *RedisStatsWriter) AddUser(ctx context.Context, token, distinctId string) error {
	key := userKey(token)
	return w.AddKey(ctx, key, distinctId, userKeyTTL, "add_user")
}

func (w *RedisStatsWriter) AddSession(ctx context.Context, token, sessionId string) error {
	key := sessionKey(token)
	return w.AddKey(ctx, key, sessionId, sessionKeyTTL, "add_session")
}

func (w *RedisStatsWriter) GetUserCount(ctx context.Context, token string) (int64, error) {
	key := userKey(token)
	return w.GetCount(ctx, key, userKeyTTL, "user_count")
}

func (w *RedisStatsWriter) GetSessionCount(ctx context.Context, token string) (int64, error) {
	key := sessionKey(token)
	return w.GetCount(ctx, key, sessionKeyTTL, "session_count")
}

func (w *RedisStatsWriter) AddKey(ctx context.Context, key string, memberId string, ttl time.Duration, metricsLabel string) error {
	start := time.Now()

	now, err := w.now(ctx)
	if err != nil {
		metrics.RedisErrors.WithLabelValues(metricsLabel).Inc()
		return err
	}

	pipe := w.client.Pipeline()
	pipe.ZAdd(ctx, key, redis.Z{Score: float64(now.Unix()), Member: memberId})
	pipe.Expire(ctx, key, ttl)
	_, err = pipe.Exec(ctx)

	metrics.RedisLatency.WithLabelValues(metricsLabel).Observe(time.Since(start).Seconds())
	if err != nil {
		metrics.RedisErrors.WithLabelValues(metricsLabel).Inc()
	}
	return err
}

func (w *RedisStatsWriter) GetCount(ctx context.Context, key string, ttl time.Duration, metricsLabel string) (int64, error) {
	start := time.Now()

	now, err := w.now(ctx)
	if err != nil {
		metrics.RedisErrors.WithLabelValues(metricsLabel).Inc()
		return 0, err
	}
	cutoff := float64(now.Add(-ttl).Unix())

	pipe := w.client.Pipeline()
	pipe.ZRemRangeByScore(ctx, key, "-inf", fmt.Sprintf("%f", cutoff))
	cardCmd := pipe.ZCard(ctx, key)
	_, err = pipe.Exec(ctx)

	metrics.RedisLatency.WithLabelValues(metricsLabel).Observe(time.Since(start).Seconds())
	if err != nil {
		metrics.RedisErrors.WithLabelValues(metricsLabel).Inc()
		return 0, err
	}
	return cardCmd.Val(), nil
}

func (w *RedisStatsWriter) Close() error {
	if c, ok := w.client.(interface{ Close() error }); ok {
		return c.Close()
	}
	return nil
}

// Testing helper
func NewRedisStatsWriterFromClient(client redis.Cmdable) *RedisStatsWriter {
	return &RedisStatsWriter{client: client}
}
