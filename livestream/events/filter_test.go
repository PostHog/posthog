package events

import (
	json "encoding/json"
	"testing"
	"time"

	"sync/atomic"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestNewFilter(t *testing.T) {
	subChan := make(chan Subscription)
	unSubChan := make(chan Subscription)
	inboundChan := make(chan PostHogEvent)

	filter := NewFilter(subChan, unSubChan, inboundChan)

	assert.NotNil(t, filter)
	assert.Equal(t, subChan, filter.SubChan)
	assert.Equal(t, unSubChan, filter.UnSubChan)
	assert.Equal(t, inboundChan, filter.inboundChan)
	assert.Empty(t, filter.subs)
}

func TestRemoveSubscription(t *testing.T) {
	subs := []Subscription{
		{SubID: 1},
		{SubID: 2},
		{SubID: 3},
	}

	result := removeSubscription(2, subs)

	assert.Len(t, result, 2)
	assert.Equal(t, uint64(1), result[0].SubID)
	assert.Equal(t, uint64(3), result[1].SubID)
}

func TestUuidFromDistinctId(t *testing.T) {
	result1 := uuidFromDistinctId(1, "user1")
	result2 := uuidFromDistinctId(1, "user1")
	result3 := uuidFromDistinctId(2, "user1")

	assert.NotEmpty(t, result1)
	assert.Equal(t, result1, result2)
	assert.NotEqual(t, result1, result3)
	assert.Empty(t, uuidFromDistinctId(0, "user1"))
	assert.Empty(t, uuidFromDistinctId(1, ""))
}

func TestConvertToResponseGeoEvent(t *testing.T) {
	event := PostHogEvent{
		Lat: 40.7128,
		Lng: -74.0060,
	}

	result := convertToResponseGeoEvent(event)

	assert.Equal(t, 40.7128, result.Lat)
	assert.Equal(t, -74.0060, result.Lng)
	assert.Equal(t, uint(1), result.Count)
}

func TestConvertToResponsePostHogEvent(t *testing.T) {
	timestamp := "2023-01-01T00:00:00Z"
	event := PostHogEvent{
		Uuid:       "123",
		Timestamp:  timestamp,
		DistinctId: "user1",
		Event:      "pageview",
		Properties: map[string]interface{}{"url": "https://example.com"},
	}

	result := convertToResponsePostHogEvent(event, 1)

	assert.Equal(t, "123", result.Uuid)
	assert.Equal(t, "2023-01-01T00:00:00Z", result.Timestamp)
	assert.Equal(t, "user1", result.DistinctId)
	assert.NotEmpty(t, result.PersonId)
	assert.Equal(t, "pageview", result.Event)
	assert.Equal(t, "https://example.com", result.Properties["url"])
}

func TestFilterRun(t *testing.T) {
	subChan := make(chan Subscription)
	unSubChan := make(chan Subscription)
	inboundChan := make(chan PostHogEvent)

	filter := NewFilter(subChan, unSubChan, inboundChan)

	go filter.Run()

	// Test subscription
	eventChan := make(chan interface{}, 1)
	sub := Subscription{
		SubID:       1,
		TeamId:      1,
		Token:       "token1",
		DistinctId:  "user1",
		EventTypes:  []string{"pageview"},
		EventChan:   eventChan,
		ShouldClose: &atomic.Bool{},
	}
	subChan <- sub

	// Wait for subscription to be processed
	time.Sleep(10 * time.Millisecond)

	// Test event filtering
	timestamp := "2023-01-01T00:00:00Z"
	event := PostHogEvent{
		Uuid:       "123",
		Timestamp:  timestamp,
		DistinctId: "user1",
		Token:      "token1",
		Event:      "pageview",
		Properties: map[string]interface{}{"url": "https://example.com"},
	}
	inboundChan <- event

	// Wait for event to be processed
	select {
	case receivedEvent := <-eventChan:
		responseEvent, ok := receivedEvent.(ResponsePostHogEvent)
		require.True(t, ok)
		assert.Equal(t, "123", responseEvent.Uuid)
		assert.Equal(t, "user1", responseEvent.DistinctId)
		assert.Equal(t, "pageview", responseEvent.Event)
	case <-time.After(100 * time.Millisecond):
		t.Fatal("Timed out waiting for event")
	}

	// Test unsubscription
	unSubChan <- sub

	// Wait for unsubscription to be processed
	time.Sleep(10 * time.Millisecond)

	assert.Empty(t, filter.subs)
}

func TestFilterRunWithGeoEvent(t *testing.T) {
	subChan := make(chan Subscription)
	unSubChan := make(chan Subscription)
	inboundChan := make(chan PostHogEvent)

	filter := NewFilter(subChan, unSubChan, inboundChan)

	go filter.Run()

	// Test subscription with Geo enabled
	eventChan := make(chan interface{}, 1)
	sub := Subscription{
		SubID:       1,
		TeamId:      1,
		Geo:         true,
		EventChan:   eventChan,
		ShouldClose: &atomic.Bool{},
	}
	subChan <- sub

	// Wait for subscription to be processed
	time.Sleep(10 * time.Millisecond)

	// Test geo event filtering
	event := PostHogEvent{
		Lat: 40.7128,
		Lng: -74.0060,
	}
	inboundChan <- event

	// Wait for event to be processed
	select {
	case receivedEvent := <-eventChan:
		geoEvent, ok := receivedEvent.(ResponseGeoEvent)
		require.True(t, ok)
		assert.Equal(t, 40.7128, geoEvent.Lat)
		assert.Equal(t, -74.0060, geoEvent.Lng)
		assert.Equal(t, uint(1), geoEvent.Count)
	case <-time.After(100 * time.Millisecond):
		t.Fatal("Timed out waiting for geo event")
	}
}

func TestResponsePostHogEvent_MarshalJSON(t *testing.T) {
	event := ResponsePostHogEvent{
		Uuid:       "123",
		Timestamp:  "2023-01-01T00:00:00Z",
		DistinctId: "user1",
		PersonId:   "person1",
		Event:      "pageview",
		Properties: map[string]interface{}{"url": "https://example.com"},
	}

	json, err := json.Marshal(event)
	require.NoError(t, err)
	assert.JSONEq(t, `{"uuid":"123","timestamp":"2023-01-01T00:00:00Z","distinct_id":"user1","person_id":"person1","event":"pageview","properties":{"url":"https://example.com"}}`, string(json))
}
