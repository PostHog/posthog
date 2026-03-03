//go:build integration

package events

import (
	"context"
	"fmt"
	"testing"
	"time"

	"github.com/redis/rueidis"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func waitForEvent(t *testing.T, ch chan interface{}, timeout time.Duration) interface{} {
	t.Helper()
	select {
	case msg := <-ch:
		return msg
	case <-time.After(timeout):
		t.Fatal("timed out waiting for event")
		return nil
	}
}

func assertNoEvent(t *testing.T, ch chan interface{}, wait time.Duration) {
	t.Helper()
	select {
	case msg := <-ch:
		t.Fatalf("expected no event but got: %v", msg)
	case <-time.After(wait):
	}
}

func verifyMultipleShards(t *testing.T, client rueidis.Client, tokens []string) {
	t.Helper()
	ctx := context.Background()
	slots := make(map[int64]bool)
	for _, token := range tokens {
		ch := channelName(token)
		result := client.Do(ctx, client.B().ClusterKeyslot().Key(ch).Build())
		slot, err := result.AsInt64()
		require.NoError(t, err, "CLUSTER KEYSLOT for %s", ch)
		slots[slot] = true
	}
	require.GreaterOrEqual(t, len(slots), 2,
		"tokens should hash to at least 2 different slots to test cross-shard delivery, got slots: %v", slots)
}

func startRouter(t *testing.T) (
	broker *RedisEventBroker,
	subChan chan Subscription,
	unSubChan chan Subscription,
	cancel context.CancelFunc,
) {
	t.Helper()

	routerClient := NewIntegrationTestClient(t)
	pubClient := NewIntegrationTestClient(t)

	broker = NewRedisEventBrokerFromClient(pubClient)

	subChan = make(chan Subscription, 16)
	unSubChan = make(chan Subscription, 16)

	router := NewTokenRouter(routerClient, subChan, unSubChan)

	ctx, cancel := context.WithCancel(context.Background())
	go router.Run(ctx)

	t.Cleanup(func() {
		cancel()
		broker.Close()
	})

	return broker, subChan, unSubChan, cancel
}

func TestRedisShardedPubSub(t *testing.T) {
	client := NewIntegrationTestClient(t)
	client.Close()

	t.Run("multi-shard delivery", func(t *testing.T) {
		broker, subChan, _, _ := startRouter(t)

		tokens := []string{"token_0", "token_1", "token_2", "token_3"}
		verifyClient := NewIntegrationTestClient(t)
		verifyMultipleShards(t, verifyClient, tokens)
		verifyClient.Close()

		subs := make([]Subscription, len(tokens))
		for i, token := range tokens {
			subs[i] = makeTestSub(uint64(i+1), token)
			subChan <- subs[i]
		}

		time.Sleep(500 * time.Millisecond)

		ctx := context.Background()
		for _, token := range tokens {
			broker.Publish(ctx, PostHogEvent{
				Token:      token,
				Event:      "$pageview",
				Uuid:       fmt.Sprintf("uuid-%s", token),
				DistinctId: "user-1",
			})
		}

		for i, token := range tokens {
			msg := waitForEvent(t, subs[i].EventChan, 3*time.Second)
			evt, ok := msg.(ResponsePostHogEvent)
			require.True(t, ok, "expected ResponsePostHogEvent for %s", token)
			assert.Equal(t, fmt.Sprintf("uuid-%s", token), evt.Uuid)
		}
	})

	t.Run("cross-token isolation", func(t *testing.T) {
		broker, subChan, _, _ := startRouter(t)

		subA := makeTestSub(1, "iso_token_a")
		subB := makeTestSub(2, "iso_token_b")
		subChan <- subA
		subChan <- subB

		time.Sleep(500 * time.Millisecond)

		ctx := context.Background()
		broker.Publish(ctx, PostHogEvent{
			Token:      "iso_token_a",
			Event:      "$pageview",
			Uuid:       "uuid-a",
			DistinctId: "user-1",
		})

		waitForEvent(t, subA.EventChan, 3*time.Second)
		assertNoEvent(t, subB.EventChan, 500*time.Millisecond)
	})

	t.Run("multiple subscribers same token", func(t *testing.T) {
		broker, subChan, _, _ := startRouter(t)

		sub1 := makeTestSub(1, "fan_token")
		sub2 := makeTestSub(2, "fan_token")
		subChan <- sub1
		subChan <- sub2

		time.Sleep(500 * time.Millisecond)

		ctx := context.Background()
		broker.Publish(ctx, PostHogEvent{
			Token:      "fan_token",
			Event:      "$pageview",
			Uuid:       "uuid-fan",
			DistinctId: "user-1",
		})

		msg1 := waitForEvent(t, sub1.EventChan, 3*time.Second)
		msg2 := waitForEvent(t, sub2.EventChan, 3*time.Second)

		evt1, ok := msg1.(ResponsePostHogEvent)
		require.True(t, ok)
		evt2, ok := msg2.(ResponsePostHogEvent)
		require.True(t, ok)

		assert.Equal(t, "uuid-fan", evt1.Uuid)
		assert.Equal(t, "uuid-fan", evt2.Uuid)
	})

	t.Run("full round-trip with filtering", func(t *testing.T) {
		broker, subChan, _, _ := startRouter(t)

		subFiltered := makeTestSub(1, "filter_token", func(s *Subscription) {
			s.DistinctId = "target-user"
			s.EventTypes = []string{"$pageview"}
		})
		subWildcard := makeTestSub(2, "filter_token")
		subChan <- subFiltered
		subChan <- subWildcard

		time.Sleep(500 * time.Millisecond)

		ctx := context.Background()

		broker.Publish(ctx, PostHogEvent{
			Token:      "filter_token",
			Event:      "$pageview",
			Uuid:       "uuid-match",
			DistinctId: "target-user",
			Properties: map[string]interface{}{"url": "https://example.com"},
		})

		broker.Publish(ctx, PostHogEvent{
			Token:      "filter_token",
			Event:      "$pageview",
			Uuid:       "uuid-wrong-user",
			DistinctId: "other-user",
		})

		broker.Publish(ctx, PostHogEvent{
			Token:      "filter_token",
			Event:      "$identify",
			Uuid:       "uuid-wrong-event",
			DistinctId: "target-user",
		})

		filteredMsg := waitForEvent(t, subFiltered.EventChan, 3*time.Second)
		filteredEvt, ok := filteredMsg.(ResponsePostHogEvent)
		require.True(t, ok)
		assert.Equal(t, "uuid-match", filteredEvt.Uuid)
		assert.Equal(t, "target-user", filteredEvt.DistinctId)
		assert.Equal(t, map[string]interface{}{"url": "https://example.com"}, filteredEvt.Properties)
		assertNoEvent(t, subFiltered.EventChan, 500*time.Millisecond)

		received := make(map[string]bool)
		for range 3 {
			msg := waitForEvent(t, subWildcard.EventChan, 3*time.Second)
			evt, ok := msg.(ResponsePostHogEvent)
			require.True(t, ok)
			received[evt.Uuid] = true
		}
		assert.True(t, received["uuid-match"])
		assert.True(t, received["uuid-wrong-user"])
		assert.True(t, received["uuid-wrong-event"])
	})
}
