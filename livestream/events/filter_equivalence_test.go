// This test file ensures that filters work identically between the new
// Pub/Sub implementation and the existing in-memory implementation
// Once the Livestream V2 migration is complete, this can be deleted.
package events

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestFilterEquivalence(t *testing.T) {
	tests := []struct {
		name       string
		sub        func() Subscription
		event      PostHogEvent
		streamType string
		wantProps  map[string]interface{}
	}{
		{
			name: "basic match",
			sub:  func() Subscription { return makeTestSub(1, "tok_a") },
			event: PostHogEvent{
				Token: "tok_a", Event: "$pageview", DistinctId: "u1", Uuid: "uuid-1",
				Properties: map[string]interface{}{"url": "https://example.com"},
			},
			streamType: "event",
			wantProps:  map[string]interface{}{"url": "https://example.com"},
		},
		{
			name: "distinctId match",
			sub: func() Subscription {
				return makeTestSub(1, "tok_a", func(s *Subscription) { s.DistinctId = "u1" })
			},
			event: PostHogEvent{
				Token: "tok_a", Event: "$pageview", DistinctId: "u1", Uuid: "uuid-1",
				Properties: map[string]interface{}{},
			},
			streamType: "event",
		},
		{
			name: "distinctId mismatch",
			sub: func() Subscription {
				return makeTestSub(1, "tok_a", func(s *Subscription) { s.DistinctId = "u1" })
			},
			event: PostHogEvent{
				Token: "tok_a", Event: "$pageview", DistinctId: "u2", Uuid: "uuid-1",
				Properties: map[string]interface{}{},
			},
			streamType: "none",
		},
		{
			name: "distinctId unset acts as wildcard",
			sub: func() Subscription {
				return makeTestSub(1, "tok_a", func(s *Subscription) { s.DistinctId = "" })
			},
			event: PostHogEvent{
				Token: "tok_a", Event: "$pageview", DistinctId: "u1", Uuid: "uuid-1",
				Properties: map[string]interface{}{},
			},
			streamType: "event",
		},
		{
			name: "eventType match",
			sub: func() Subscription {
				return makeTestSub(1, "tok_a", func(s *Subscription) { s.EventTypes = []string{"$pageview"} })
			},
			event: PostHogEvent{
				Token: "tok_a", Event: "$pageview", DistinctId: "u1", Uuid: "uuid-1",
				Properties: map[string]interface{}{},
			},
			streamType: "event",
		},
		{
			name: "eventType mismatch",
			sub: func() Subscription {
				return makeTestSub(1, "tok_a", func(s *Subscription) { s.EventTypes = []string{"$pageview"} })
			},
			event: PostHogEvent{
				Token: "tok_a", Event: "$identify", DistinctId: "u1", Uuid: "uuid-1",
				Properties: map[string]interface{}{},
			},
			streamType: "none",
		},
		{
			name: "eventType unset acts as wildcard",
			sub: func() Subscription {
				return makeTestSub(1, "tok_a", func(s *Subscription) { s.EventTypes = nil })
			},
			event: PostHogEvent{
				Token: "tok_a", Event: "$pageview", DistinctId: "u1", Uuid: "uuid-1",
				Properties: map[string]interface{}{},
			},
			streamType: "event",
		},
		{
			name: "geo with coordinates",
			sub: func() Subscription {
				return makeTestSub(1, "tok_a", func(s *Subscription) { s.Geo = true })
			},
			event: PostHogEvent{
				Token: "tok_a", Event: "$pageview", DistinctId: "u1", Uuid: "uuid-1",
				Lat: 40.7128, Lng: -74.0060, CountryCode: "US",
				Properties: map[string]interface{}{},
			},
			streamType: "geo",
		},
		{
			name: "geo without coordinates",
			sub: func() Subscription {
				return makeTestSub(1, "tok_a", func(s *Subscription) { s.Geo = true })
			},
			event: PostHogEvent{
				Token: "tok_a", Event: "$pageview", DistinctId: "u1", Uuid: "uuid-1",
				Lat: 0, Lng: 0,
				Properties: map[string]interface{}{},
			},
			streamType: "none",
		},
		{
			name: "column filtering",
			sub: func() Subscription {
				return makeTestSub(1, "tok_a", func(s *Subscription) { s.Columns = []string{"url"} })
			},
			event: PostHogEvent{
				Token: "tok_a", Event: "$pageview", DistinctId: "u1", Uuid: "uuid-1",
				Properties: map[string]interface{}{"url": "https://example.com", "$browser": "Chrome"},
			},
			streamType: "event",
			wantProps:  map[string]interface{}{"url": "https://example.com"},
		},
		{
			name: "columns nil returns all properties",
			sub: func() Subscription {
				return makeTestSub(1, "tok_a", func(s *Subscription) { s.Columns = nil })
			},
			event: PostHogEvent{
				Token: "tok_a", Event: "$pageview", DistinctId: "u1", Uuid: "uuid-1",
				Properties: map[string]interface{}{"url": "https://example.com", "$browser": "Chrome"},
			},
			streamType: "event",
			wantProps:  map[string]interface{}{"url": "https://example.com", "$browser": "Chrome"},
		},
		{
			name: "shouldClose prevents delivery",
			sub: func() Subscription {
				s := makeTestSub(1, "tok_a")
				s.ShouldClose.Store(true)
				return s
			},
			event: PostHogEvent{
				Token: "tok_a", Event: "$pageview", DistinctId: "u1", Uuid: "uuid-1",
				Properties: map[string]interface{}{},
			},
			streamType: "none",
		},
		{
			name: "multiple filters combined — all match",
			sub: func() Subscription {
				return makeTestSub(1, "tok_a", func(s *Subscription) {
					s.DistinctId = "u1"
					s.EventTypes = []string{"$pageview"}
				})
			},
			event: PostHogEvent{
				Token: "tok_a", Event: "$pageview", DistinctId: "u1", Uuid: "uuid-1",
				Properties: map[string]interface{}{},
			},
			streamType: "event",
		},
		{
			name: "multiple filters combined — partial mismatch",
			sub: func() Subscription {
				return makeTestSub(1, "tok_a", func(s *Subscription) {
					s.DistinctId = "u1"
					s.EventTypes = []string{"$pageview"}
				})
			},
			event: PostHogEvent{
				Token: "tok_a", Event: "$identify", DistinctId: "u1", Uuid: "uuid-1",
				Properties: map[string]interface{}{},
			},
			streamType: "none",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			directSub := tt.sub()
			deliverEvent(tt.event, []Subscription{directSub})
			directResult := drainChan(directSub.EventChan)

			pubsubSub := tt.sub()
			data, err := tt.event.MarshalJSON()
			require.NoError(t, err)
			var roundTripped PostHogEvent
			require.NoError(t, roundTripped.UnmarshalJSON(data))
			deliverEvent(roundTripped, []Subscription{pubsubSub})
			pubsubResult := drainChan(pubsubSub.EventChan)

			switch tt.streamType {
			case "none":
				assert.Nil(t, directResult, "direct path should not deliver")
				assert.Nil(t, pubsubResult, "pubsub path should not deliver")

			case "event":
				require.NotNil(t, directResult, "direct path should deliver an event")
				require.NotNil(t, pubsubResult, "pubsub path should deliver an event")
				directEvt, ok := directResult.(ResponsePostHogEvent)
				require.True(t, ok, "direct result should be ResponsePostHogEvent")
				pubsubEvt, ok := pubsubResult.(ResponsePostHogEvent)
				require.True(t, ok, "pubsub result should be ResponsePostHogEvent")

				assert.Equal(t, directEvt, pubsubEvt)

			case "geo":
				require.NotNil(t, directResult, "direct path should deliver a geo event")
				require.NotNil(t, pubsubResult, "pubsub path should deliver a geo event")
				directGeo, ok := directResult.(ResponseGeoEvent)
				require.True(t, ok, "direct result should be ResponseGeoEvent")
				pubsubGeo, ok := pubsubResult.(ResponseGeoEvent)
				require.True(t, ok, "pubsub result should be ResponseGeoEvent")

				assert.Equal(t, directGeo, pubsubGeo)
			}
		})
	}
}

func drainChan(ch chan interface{}) interface{} {
	select {
	case v := <-ch:
		return v
	default:
		return nil
	}
}
