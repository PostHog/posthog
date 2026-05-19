/*
StatsInRedis provides a shared storage backed by Redis.
It enables the /stats endpoint to serve consistent user
and session counts across multiple service instances by
adding tokens to a sorted set with a short-lived TTL.

Redis pipelines (DoMulti) are used to batch multiple commands into a single round-trip.
Each pipeline targets a single key, so all commands hit the same hash slot
and are safe by default in cluster mode.
*/
package events

import (
	"context"
	"fmt"
	"log"
	"maps"
	"strconv"
	"sync"
	"time"

	"github.com/posthog/posthog/livestream/configs"
	"github.com/posthog/posthog/livestream/metrics"
	"github.com/redis/rueidis"
)

const (
	userKeyTTL    = 60 * time.Second
	sessionKeyTTL = 5 * time.Minute
)

type StatsInRedis struct {
	client rueidis.Client
}

// Creates a Redis-backed stats store from the given config.
func NewStatsInRedis(cfg configs.RedisConfig) (*StatsInRedis, error) {
	client, err := newRedisClient(cfg)
	if err != nil {
		return nil, err
	}
	return &StatsInRedis{client: client}, nil
}

// Client returns the underlying Redis client.
func (s *StatsInRedis) Client() rueidis.Client {
	return s.client
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

// Close closes the underlying Redis connection.
func (s *StatsInRedis) Close() {
	s.client.Close()
}

func userKey(token string) string {
	return fmt.Sprintf("livestream:users:%s", token)
}

func sessionKey(token string) string {
	return fmt.Sprintf("livestream:sessions:%s", token)
}

func cutoffScore(ttl time.Duration) string {
	return strconv.FormatInt(time.Now().Add(-ttl).Unix(), 10)
}

// Adds a member to a sorted set scored by the current timestamp, prunes stale entries older than ttl, then sets the key expiry.
func (s *StatsInRedis) addKey(ctx context.Context, key string, memberId string, ttl time.Duration, metricsLabel string) error {
	now := time.Now()
	score := float64(now.Unix())
	cmds := make(rueidis.Commands, 3)
	cmds[0] = s.client.B().Zadd().Key(key).Gt().ScoreMember().ScoreMember(score, memberId).Build()
	cmds[1] = s.client.B().Zremrangebyscore().Key(key).Min("-inf").Max(cutoffScore(ttl)).Build()
	cmds[2] = s.client.B().Expire().Key(key).Seconds(int64(ttl.Seconds())).Build()

	results := s.client.DoMulti(ctx, cmds...)

	metrics.RedisLatency.WithLabelValues(metricsLabel).Observe(time.Since(now).Seconds())

	for _, r := range results {
		if err := r.Error(); err != nil {
			metrics.RedisErrors.WithLabelValues(metricsLabel).Inc()
			return err
		}
	}
	return nil
}

// Returns a sliding-window count by first pruning entries older than the TTL then counting survivors
func (s *StatsInRedis) getCount(ctx context.Context, key string, ttl time.Duration, metricsLabel string) (int64, error) {
	now := time.Now()
	cmds := make(rueidis.Commands, 2)
	cmds[0] = s.client.B().Zremrangebyscore().Key(key).Min("-inf").Max(cutoffScore(ttl)).Build()
	cmds[1] = s.client.B().Zcard().Key(key).Build()

	results := s.client.DoMulti(ctx, cmds...)

	metrics.RedisLatency.WithLabelValues(metricsLabel).Observe(time.Since(now).Seconds())

	if err := results[0].Error(); err != nil {
		metrics.RedisErrors.WithLabelValues(metricsLabel).Inc()
		return 0, err
	}

	count, err := results[1].AsInt64()
	if err != nil {
		metrics.RedisErrors.WithLabelValues(metricsLabel).Inc()
		return 0, err
	}
	return count, nil
}

// Writes a batch of user updates to Redis.
// pending maps token: (distinctID: score).
func (s *StatsInRedis) FlushUsers(ctx context.Context, pending map[string]map[string]float64) {
	s.flushKeys(ctx, pending, userKeyTTL, "batch_add_user", userKey)
}

// Writes a batch of session updates to Redis.
// pending maps token: (sessionID: score).
func (s *StatsInRedis) FlushSessions(ctx context.Context, pending map[string]map[string]float64) {
	s.flushKeys(ctx, pending, sessionKeyTTL, "batch_add_session", sessionKey)
}

func (s *StatsInRedis) flushKeys(ctx context.Context, pending map[string]map[string]float64, ttl time.Duration, metricsLabel string, keyFn func(string) string) {
	if len(pending) == 0 {
		return
	}

	metrics.RedisFlushBatchSize.WithLabelValues(metricsLabel).Observe(float64(len(pending)))
	metrics.RedisFlushTotal.WithLabelValues(metricsLabel).Inc()

	now := time.Now()
	cutoff := cutoffScore(ttl)
	var wg sync.WaitGroup

	for token, members := range pending {
		wg.Add(1)
		go func(token string, members map[string]float64) {
			defer wg.Done()

			key := keyFn(token)

			cmds := make(rueidis.Commands, 3)
			cmds[0] = s.client.B().Zadd().Key(key).Gt().ScoreMember().ScoreMemberIter(maps.All(members)).Build()
			cmds[1] = s.client.B().Zremrangebyscore().Key(key).Min("-inf").Max(cutoff).Build()
			cmds[2] = s.client.B().Expire().Key(key).Seconds(int64(ttl.Seconds())).Build()

			results := s.client.DoMulti(ctx, cmds...)
			for _, r := range results {
				if err := r.Error(); err != nil {
					log.Printf("Redis flush error for key %s: %v", key, err)
					metrics.RedisErrors.WithLabelValues(metricsLabel).Inc()
				}
			}
		}(token, members)
	}

	wg.Wait()
	metrics.RedisLatency.WithLabelValues(metricsLabel).Observe(time.Since(now).Seconds())
}

// Testing helper
func NewStatsInRedisFromClient(client rueidis.Client) *StatsInRedis {
	return &StatsInRedis{client: client}
}
