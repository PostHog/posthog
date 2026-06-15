package events

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestPostHogEventRoundTrip(t *testing.T) {
	tests := []struct {
		name  string
		input PostHogEvent
	}{
		{
			name: "all fields populated",
			input: PostHogEvent{
				Token:       "tok_abc",
				Event:       "$pageview",
				Properties:  map[string]interface{}{"url": "https://example.com", "$browser": "Chrome"},
				Timestamp:   "2026-01-01T00:00:00Z",
				Uuid:        "550e8400-e29b-41d4-a716-446655440000",
				DistinctId:  "user-42",
				Lat:         40.712776,
				Lng:         -74.005974,
				CountryCode: "US",
			},
		},
		{
			name: "numeric property values survive as float64",
			input: PostHogEvent{
				Token:      "tok_abc",
				Event:      "$pageview",
				Properties: map[string]interface{}{"count": float64(42), "price": 9.99},
				Uuid:       "uuid-1",
				DistinctId: "user-1",
			},
		},
		{
			name: "empty properties",
			input: PostHogEvent{
				Token:      "tok_abc",
				Event:      "$identify",
				Properties: map[string]interface{}{},
				Uuid:       "uuid-2",
				DistinctId: "user-2",
			},
		},
		{
			name: "nil properties",
			input: PostHogEvent{
				Token:      "tok_abc",
				Event:      "$identify",
				Properties: nil,
				Uuid:       "uuid-3",
				DistinctId: "user-3",
			},
		},
		{
			name: "zero lat/lng",
			input: PostHogEvent{
				Token:      "tok_abc",
				Event:      "$pageview",
				Properties: map[string]interface{}{},
				Uuid:       "uuid-4",
				DistinctId: "user-4",
				Lat:        0.0,
				Lng:        0.0,
			},
		},
		{
			name: "timestamp as numeric",
			input: PostHogEvent{
				Token:      "tok_abc",
				Event:      "$pageview",
				Properties: map[string]interface{}{},
				Timestamp:  float64(1704067200),
				Uuid:       "uuid-5",
				DistinctId: "user-5",
			},
		},
		{
			name: "nested properties",
			input: PostHogEvent{
				Token: "tok_abc",
				Event: "$pageview",
				Properties: map[string]interface{}{
					"nested": map[string]interface{}{"key": "value"},
					"list":   []interface{}{"a", "b"},
				},
				Uuid:       "uuid-6",
				DistinctId: "user-6",
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			data, err := tt.input.MarshalJSON()
			require.NoError(t, err)

			var result PostHogEvent
			err = result.UnmarshalJSON(data)
			require.NoError(t, err)

			assert.Equal(t, tt.input.Token, result.Token)
			assert.Equal(t, tt.input.Event, result.Event)
			assert.Equal(t, tt.input.Uuid, result.Uuid)
			assert.Equal(t, tt.input.DistinctId, result.DistinctId)
			assert.Equal(t, tt.input.Lat, result.Lat)
			assert.Equal(t, tt.input.Lng, result.Lng)
			assert.Equal(t, tt.input.CountryCode, result.CountryCode)

			if tt.input.Properties == nil {
				assert.True(t, len(result.Properties) == 0)
			} else {
				assert.Equal(t, tt.input.Properties, result.Properties)
			}

			if tt.input.Timestamp != nil {
				assert.NotNil(t, result.Timestamp)
			}
		})
	}
}
