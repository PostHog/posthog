package events

import (
	"context"
	"testing"

	"github.com/stretchr/testify/assert"
)

type fakeGate struct {
	allow map[string]bool
	def   bool
}

func (f fakeGate) ShouldPublish(token string) bool {
	if v, ok := f.allow[token]; ok {
		return v
	}
	return f.def
}

func TestBrokerPublish_SubscriberAwareGating(t *testing.T) {
	event := func(token string) PostHogEvent {
		return PostHogEvent{Token: token, Event: "$pageview", Uuid: "uuid-1", DistinctId: "user-1"}
	}

	t.Run("skips and does not buffer when no subscriber", func(t *testing.T) {
		b := NewRedisEventBrokerFromClient(nil, 8, 1)
		b.SetPublishGate(fakeGate{def: false})

		b.Publish(context.Background(), event("tok"))
		assert.Equal(t, 0, len(b.publishCh), "unsubscribed event must not enter the publish buffer")
	})

	t.Run("buffers when the token has a subscriber", func(t *testing.T) {
		b := NewRedisEventBrokerFromClient(nil, 8, 1)
		b.SetPublishGate(fakeGate{allow: map[string]bool{"tok": true}})

		b.Publish(context.Background(), event("tok"))
		assert.Equal(t, 1, len(b.publishCh))
	})

	t.Run("no gate buffers everything (feature off)", func(t *testing.T) {
		b := NewRedisEventBrokerFromClient(nil, 8, 1)

		b.Publish(context.Background(), event("tok"))
		assert.Equal(t, 1, len(b.publishCh), "with the gate off, behavior is unchanged")
	})

	t.Run("empty token is always dropped", func(t *testing.T) {
		b := NewRedisEventBrokerFromClient(nil, 8, 1)
		b.SetPublishGate(fakeGate{def: true})

		b.Publish(context.Background(), event(""))
		assert.Equal(t, 0, len(b.publishCh))
	})
}
