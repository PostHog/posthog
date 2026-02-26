/*
	StatsInRedis provides a shared storage backed by Redis.
	It enables the /stats endpoint to serve consistent user
	and session counts across multiple service instances by
	adding tokens to a sorted set with a short-lived TTL.

	Redis pipelines are used to batch multiple commands into a single round-trip.
	Each pipeline targets a single key, so all commands hit the same hash slot
	and are safe by default in cluster mode.
*/
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

type StatsInRedis struct {
	client redis.Cmdable
}

// Creates a Redis-backed stats store from the given config.
func NewStatsInRedis(cfg configs.RedisConfig) (*StatsInRedis, error) {
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

	return &StatsInRedis{client: client}, nil
}

// Adds a distinct user to a Redis sorted set for the given project token,
// scored by the current timestamp. The key auto-expires after userKeyTTL.
func (s *StatsInRedis) AddUser(ctx context.Context, token, distinctId string) error {
	key := userKey(token)
	return s.addKey(ctx, key, distinctId, userKeyTTL, "add_user")
}

// Adds a session ID to a Redis sorted set for the given project token,
// scored by the current timestamp. The key auto-expires after sessionKeyTTL.
func (s *StatsInRedis) AddSession(ctx context.Context, token, sessionId string) error {
	key := sessionKey(token)
	return s.addKey(ctx, key, sessionId, sessionKeyTTL, "add_session")
}

// Returns the number of distinct users seen within the last userKeyTTL window for the given token.
func (s *StatsInRedis) GetUserCount(ctx context.Context, token string) (int64, error) {
	key := userKey(token)
	return s.getCount(ctx, key, userKeyTTL, "user_count")
}

// Returns the number of active sessions within the last sessionKeyTTL window for the given token.
func (s *StatsInRedis) GetSessionCount(ctx context.Context, token string) (int64, error) {
	key := sessionKey(token)
	return s.getCount(ctx, key, sessionKeyTTL, "session_count")
}

// Close closes the underlying Redis connection if the client supports it.
func (s *StatsInRedis) Close() error {
	if c, ok := s.client.(interface{ Close() error }); ok {
		return c.Close()
	}
	return nil
}

func userKey(token string) string {
	return fmt.Sprintf("livestream:users:%s", token)
}

func sessionKey(token string) string {
	return fmt.Sprintf("livestream:sessions:%s", token)
}

// Adds a member to a sorted set scored by the current timestamp, then sets the key expiry. 
func (s *StatsInRedis) addKey(ctx context.Context, key string, memberId string, ttl time.Duration, metricsLabel string) error {
	now := time.Now()

	pipe := s.client.Pipeline()
	pipe.ZAdd(ctx, key, redis.Z{Score: float64(now.Unix()), Member: memberId})
	pipe.Expire(ctx, key, ttl)
	_, err := pipe.Exec(ctx)

	metrics.RedisLatency.WithLabelValues(metricsLabel).Observe(time.Since(now).Seconds())
	if err != nil {
		metrics.RedisErrors.WithLabelValues(metricsLabel).Inc()
	}
	return err
}

// Returns a sliding-window count by first pruning entries older than the TTL then counting survivors
func (s *StatsInRedis) getCount(ctx context.Context, key string, ttl time.Duration, metricsLabel string) (int64, error) {
	now := time.Now()
	cutoff := float64(now.Add(-ttl).Unix())

	pipe := s.client.Pipeline()
	pipe.ZRemRangeByScore(ctx, key, "-inf", fmt.Sprintf("%f", cutoff))
	cardCmd := pipe.ZCard(ctx, key)
	_, err := pipe.Exec(ctx)

	metrics.RedisLatency.WithLabelValues(metricsLabel).Observe(time.Since(now).Seconds())
	if err != nil {
		metrics.RedisErrors.WithLabelValues(metricsLabel).Inc()
		return 0, err
	}
	return cardCmd.Val(), nil
}

// Testing helper
func NewStatsInRedisFromClient(client redis.Cmdable) *StatsInRedis {
	return &StatsInRedis{client: client}
}
