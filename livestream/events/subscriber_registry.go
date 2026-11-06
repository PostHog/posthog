package events

import (
	"context"
	"log"
	"maps"
	"strconv"
	"sync"
	"time"

	"github.com/posthog/posthog/livestream/configs"
	"github.com/posthog/posthog/livestream/metrics"
	"github.com/redis/rueidis"
)

/*
SubscriberRegistry powers subscriber-aware publishing.

Without it, every consumed event is SPUBLISH'd to livestream:events:<token>, even
when no viewer is watching that token. In practice the vast majority of tokens have
no subscriber, so that publish is pure waste: it crosses AZs to the shard primary and
saturates the publish buffer.

The registry lets publishers skip tokens that nobody is watching, while never dropping
an event a viewer is actually watching:

  - Subscribers (TokenRouter) register their active tokens here on subscribe and on a
    periodic heartbeat, in a single sorted set (member = token, score = last-heartbeat
    unix seconds) in the SAME Redis/Valkey. The key auto-expires so a crashed subscriber
    ages out on its own.
  - Publishers (RedisEventBroker) keep a locally-cached snapshot of the active-token set,
    refreshed every few seconds with one cheap read (never per-event), and skip SPUBLISH
    for tokens not in the set.

Correctness (never drop a watched event) is enforced by:

  - Registering a token synchronously the moment its first subscriber connects, so the
    registry reflects it before the next publisher refresh.
  - A TTL (activeWindow) that is several heartbeats long, so a live token survives a few
    lost heartbeats.
  - A publisher-side grace, so a token that just disappeared from the registry keeps being
    published for a short while (absorbs read/prune/clock-skew races).
  - Fail-open: if the snapshot has never loaded, the last read errored, or the snapshot is
    stale, publishers publish everything. When in doubt, publish.

Single key note: like StatsInRedis, this uses one key, so in cluster mode every command
hits the same hash slot and pipelines are safe. The read/write volume is tiny (one read
per refresh interval per publisher, one pipelined write per heartbeat), so the single-slot
concentration is not a concern versus the per-event publishes it removes.
*/

const subscriberRegistryKey = "livestream:subscribers"

// Tunables for subscriber-aware publishing. The numbers below are chosen so that a live
// subscription is never starved while still skipping the ~99% of tokens nobody watches.
const (
	// A token counts as active if it was heartbeated within this window. It doubles as the
	// subscriber-side prune cutoff, so the read and the prune agree. At 3x the heartbeat
	// interval it tolerates two consecutive lost heartbeats before a live token could drop.
	// It is also the trailing grace: after the last viewer leaves, publishing continues for
	// up to this long.
	defaultRegistryActiveWindow = 30 * time.Second

	// How often subscribers re-register their active tokens.
	defaultRegistryHeartbeat = 10 * time.Second

	// How often publishers re-read the active-token snapshot. This bounds the
	// subscribe->first-publish window: a newly subscribed token is picked up within one
	// refresh interval.
	defaultRegistrySnapshotRefresh = 2 * time.Second

	// Publisher-side grace: a token that stops appearing in reads stays publishable for this
	// long. It absorbs a read landing mid-prune, brief registry blips, and clock skew between
	// a subscriber process and a publisher process.
	defaultRegistryGrace = 5 * time.Second

	// If a publisher has not refreshed the snapshot successfully within this window, it fails
	// open and publishes everything. Guards against a stalled refresher goroutine on top of
	// the immediate fail-open on any read error.
	defaultRegistryStaleAfter = 15 * time.Second
)

// SubscriberRegistry is the shared active-token registry. It is safe for concurrent use:
// ShouldPublish is called from every publish worker, refreshOnce from the refresher
// goroutine, and Heartbeat from the TokenRouter.
type SubscriberRegistry struct {
	client rueidis.Client
	key    string

	activeWindow time.Duration
	heartbeat    time.Duration
	refresh      time.Duration
	grace        time.Duration
	staleAfter   time.Duration

	// readActive reads the current active-token set. It is a field so tests can inject
	// deterministic results and errors without a live Redis.
	readActive func(ctx context.Context) ([]string, error)

	mu              sync.RWMutex
	active          map[string]struct{}  // tokens present in the last good read; publishable while the snapshot is fresh
	publishUntil    map[string]time.Time // token that just left the active set -> grace deadline
	lastGoodRefresh time.Time
	healthy         bool
}

// NewSubscriberRegistry creates a registry with its own Redis connection.
func NewSubscriberRegistry(cfg configs.RedisConfig) (*SubscriberRegistry, error) {
	client, err := newRedisClient(cfg)
	if err != nil {
		return nil, err
	}
	return newSubscriberRegistryFromClient(client), nil
}

func newSubscriberRegistryFromClient(client rueidis.Client) *SubscriberRegistry {
	r := &SubscriberRegistry{
		client:       client,
		key:          subscriberRegistryKey,
		activeWindow: defaultRegistryActiveWindow,
		heartbeat:    defaultRegistryHeartbeat,
		refresh:      defaultRegistrySnapshotRefresh,
		grace:        defaultRegistryGrace,
		staleAfter:   defaultRegistryStaleAfter,
		active:       make(map[string]struct{}),
		publishUntil: make(map[string]time.Time),
	}
	r.readActive = r.readActiveFromRedis
	return r
}

// HeartbeatInterval is how often subscribers should re-register their active tokens.
func (r *SubscriberRegistry) HeartbeatInterval() time.Duration {
	return r.heartbeat
}

// ShouldPublish reports whether an event for token must be published. It fails open
// (returns true) whenever the active set is unknown, stale, or the last read errored, so
// uncertainty never drops a watched event.
func (r *SubscriberRegistry) ShouldPublish(token string) bool {
	r.mu.RLock()
	defer r.mu.RUnlock()

	if !r.healthy || r.lastGoodRefresh.IsZero() || time.Since(r.lastGoodRefresh) > r.staleAfter {
		return true
	}

	// A token in the last good snapshot is actively watched: publish for as long as the
	// snapshot is fresh (the staleness check above bounds that), so a lagging refresh never
	// drops a watched event before the fail-open. A token that just left the snapshot keeps
	// publishing until its grace deadline, to absorb read/prune/clock-skew races.
	if _, ok := r.active[token]; ok {
		return true
	}
	deadline, ok := r.publishUntil[token]
	return ok && time.Now().Before(deadline)
}

// RunSnapshotRefresher keeps the publisher snapshot fresh until ctx is cancelled.
func (r *SubscriberRegistry) RunSnapshotRefresher(ctx context.Context) {
	if err := r.refreshOnce(ctx); err != nil {
		log.Printf("subscriber registry initial refresh: %v", err)
	}

	ticker := time.NewTicker(r.refresh)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			if err := r.refreshOnce(ctx); err != nil {
				log.Printf("subscriber registry refresh: %v", err)
			}
		}
	}
}

func (r *SubscriberRegistry) readActiveFromRedis(ctx context.Context) ([]string, error) {
	cutoff := strconv.FormatInt(time.Now().Add(-r.activeWindow).Unix(), 10)
	return r.client.Do(ctx, r.client.B().Zrangebyscore().Key(r.key).Min(cutoff).Max("+inf").Build()).AsStrSlice()
}

// refreshOnce loads the active-token set and rebuilds the publisher snapshot. On error it
// marks the snapshot unhealthy (fail open) and returns the error.
func (r *SubscriberRegistry) refreshOnce(ctx context.Context) error {
	tokens, err := r.readActive(ctx)
	now := time.Now()

	if err != nil {
		r.mu.Lock()
		r.healthy = false
		r.mu.Unlock()
		metrics.SubscriberRegistryReadErrorsTotal.Inc()
		return err
	}

	r.mu.Lock()
	active := make(map[string]struct{}, len(tokens))
	for _, t := range tokens {
		active[t] = struct{}{}
	}
	// A token that was active last refresh but is now gone starts its grace countdown from now.
	// A token already counting down keeps its original deadline, so grace measures from when a
	// token first left the active set, never longer.
	grace := make(map[string]time.Time)
	for t := range r.active {
		if _, stillActive := active[t]; !stillActive {
			grace[t] = now.Add(r.grace)
		}
	}
	for t, deadline := range r.publishUntil {
		if _, stillActive := active[t]; !stillActive && deadline.After(now) {
			grace[t] = deadline
		}
	}
	r.active = active
	r.publishUntil = grace
	r.lastGoodRefresh = now
	r.healthy = true
	r.mu.Unlock()

	metrics.SubscriberRegistryActiveTokens.Set(float64(len(tokens)))
	return nil
}

// Heartbeat registers or refreshes the given tokens as having active subscribers. Called on
// subscribe (single token) and on the periodic heartbeat (all active tokens). All commands
// target the single registry key, so they share one hash slot in cluster mode.
func (r *SubscriberRegistry) Heartbeat(ctx context.Context, tokens []string) error {
	if len(tokens) == 0 {
		return nil
	}

	now := time.Now()
	score := float64(now.Unix())
	members := make(map[string]float64, len(tokens))
	for _, t := range tokens {
		if t != "" {
			members[t] = score
		}
	}
	if len(members) == 0 {
		return nil
	}

	cutoff := strconv.FormatInt(now.Add(-r.activeWindow).Unix(), 10)
	keyTTL := int64((r.activeWindow + r.grace).Seconds())

	cmds := make(rueidis.Commands, 3)
	cmds[0] = r.client.B().Zadd().Key(r.key).Gt().ScoreMember().ScoreMemberIter(maps.All(members)).Build()
	cmds[1] = r.client.B().Zremrangebyscore().Key(r.key).Min("-inf").Max(cutoff).Build()
	cmds[2] = r.client.B().Expire().Key(r.key).Seconds(keyTTL).Build()

	for _, res := range r.client.DoMulti(ctx, cmds...) {
		if err := res.Error(); err != nil {
			return err
		}
	}
	return nil
}

// Close releases the registry's Redis connection.
func (r *SubscriberRegistry) Close() {
	r.client.Close()
}
