package events

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/redis/rueidis"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestSubscriberRegistry_ShouldPublish(t *testing.T) {
	r := newSubscriberRegistryFromClient(nil)

	// Never refreshed => fail open so startup never drops a watched event.
	assert.True(t, r.ShouldPublish("tok"))

	// Healthy snapshot with no subscribers => skip (this is the ~99% waste we remove).
	r.mu.Lock()
	r.healthy = true
	r.lastGoodRefresh = time.Now()
	r.publishUntil = map[string]time.Time{}
	r.mu.Unlock()
	assert.False(t, r.ShouldPublish("tok"))

	// A subscribed token within its window => publish; an unrelated token => skip.
	r.mu.Lock()
	r.publishUntil["tok"] = time.Now().Add(time.Second)
	r.mu.Unlock()
	assert.True(t, r.ShouldPublish("tok"))
	assert.False(t, r.ShouldPublish("other"))

	// Stale snapshot (refresher stalled) => fail open.
	r.mu.Lock()
	r.lastGoodRefresh = time.Now().Add(-2 * r.staleAfter)
	r.mu.Unlock()
	assert.True(t, r.ShouldPublish("other"))
}

func TestSubscriberRegistry_FailsOpenOnReadError(t *testing.T) {
	ctx := context.Background()
	r := newSubscriberRegistryFromClient(nil)

	// A good load first: only the registered token publishes.
	r.readActive = func(context.Context) ([]string, error) { return []string{"tok"}, nil }
	require.NoError(t, r.refreshOnce(ctx))
	assert.True(t, r.ShouldPublish("tok"))
	assert.False(t, r.ShouldPublish("other"))

	// Reads start failing: publishers must fail open and skip nothing.
	r.readActive = func(context.Context) ([]string, error) { return nil, errors.New("redis unavailable") }
	require.Error(t, r.refreshOnce(ctx))
	assert.True(t, r.ShouldPublish("tok"))
	assert.True(t, r.ShouldPublish("other"))

	// Recovery: the next good read resumes filtering.
	r.readActive = func(context.Context) ([]string, error) { return []string{"tok"}, nil }
	require.NoError(t, r.refreshOnce(ctx))
	assert.True(t, r.ShouldPublish("tok"))
	assert.False(t, r.ShouldPublish("other"))
}

func TestSubscriberRegistry_GraceWindowKeepsJustExpiredTokenPublished(t *testing.T) {
	ctx := context.Background()
	r := newSubscriberRegistryFromClient(nil)
	r.grace = 60 * time.Millisecond
	r.staleAfter = time.Hour // isolate the grace behavior from the staleness fail-open

	active := []string{"tok"}
	r.readActive = func(context.Context) ([]string, error) { return active, nil }

	require.NoError(t, r.refreshOnce(ctx))
	assert.True(t, r.ShouldPublish("tok"))

	// The token disappears from the registry (viewer left, or a brief read flap). During the
	// grace window an in-flight event for it must still be published, never dropped.
	active = nil
	require.NoError(t, r.refreshOnce(ctx))
	assert.True(t, r.ShouldPublish("tok"), "just-expired token must stay published during grace")

	// Once the grace window elapses, the token is skipped.
	time.Sleep(80 * time.Millisecond)
	require.NoError(t, r.refreshOnce(ctx))
	assert.False(t, r.ShouldPublish("tok"), "token must be skipped after the grace window")
}

func TestSubscriberRegistry_ActiveTokenStaysPublishableWhenRefreshLagsPastGrace(t *testing.T) {
	ctx := context.Background()
	r := newSubscriberRegistryFromClient(nil)
	r.grace = 20 * time.Millisecond
	r.staleAfter = time.Hour // a lagging refresh, not a stale snapshot: fail-open must not be what saves us

	r.readActive = func(context.Context) ([]string, error) { return []string{"tok"}, nil }
	require.NoError(t, r.refreshOnce(ctx))
	assert.True(t, r.ShouldPublish("tok"))

	// The refresher lags well past the grace window but stays within staleAfter. An actively
	// watched token must keep publishing the whole time, never dropped at the grace boundary.
	time.Sleep(3 * r.grace)
	assert.True(t, r.ShouldPublish("tok"), "active token must stay published when refresh lags past grace but within staleAfter")
}

// TestSubscriberRegistry_RedisRoundTrip exercises the real ZADD/ZRANGEBYSCORE path against
// an in-process Redis: a heartbeated token is seen by the publisher snapshot, an
// unregistered one is not.
func TestSubscriberRegistry_RedisRoundTrip(t *testing.T) {
	mr := miniredis.RunT(t)
	client, err := rueidis.NewClient(rueidis.ClientOption{
		InitAddress:  []string{mr.Addr()},
		DisableCache: true,
	})
	require.NoError(t, err)
	t.Cleanup(client.Close)

	ctx := context.Background()
	r := newSubscriberRegistryFromClient(client)

	// A healthy read of an empty registry => skip everything.
	require.NoError(t, r.refreshOnce(ctx))
	assert.False(t, r.ShouldPublish("tokA"))

	// Register two tokens; the snapshot must then see exactly those.
	require.NoError(t, r.Heartbeat(ctx, []string{"tokA", "tokB"}))
	require.NoError(t, r.refreshOnce(ctx))
	assert.True(t, r.ShouldPublish("tokA"))
	assert.True(t, r.ShouldPublish("tokB"))
	assert.False(t, r.ShouldPublish("tokC"))
}

func TestSubscriberRegistry_HeartbeatNoTokensIsNoop(t *testing.T) {
	// A nil client would panic if Heartbeat issued any command; it must short-circuit.
	r := newSubscriberRegistryFromClient(nil)
	require.NoError(t, r.Heartbeat(context.Background(), nil))
	require.NoError(t, r.Heartbeat(context.Background(), []string{""}))
}
