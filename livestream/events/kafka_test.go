package events

import (
	"encoding/json"
	"errors"
	"os"
	"testing"
	"time"

	"github.com/confluentinc/confluent-kafka-go/v2/kafka"
	"github.com/posthog/posthog/livestream/geo"
	"github.com/posthog/posthog/livestream/mocks"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/mock"
)

func TestPostHogKafkaConsumer_Consume(t *testing.T) {
	// Create mock objects
	mockConsumer := new(mocks.KafkaConsumerInterface)
	mockGeoLocator := new(mocks.GeoLocator)

	// Create channels
	outgoingChan := make(chan PostHogEvent, 1)
	statsChan := make(chan CountEvent, 1)

	// Create PostHogKafkaConsumer
	consumer := &PostHogKafkaConsumer{
		consumer:     mockConsumer,
		topic:        "test-topic",
		geolocator:   mockGeoLocator,
		incoming:     make(chan []byte),
		outgoingChan: outgoingChan,
		statsChan:    statsChan,
		parallel:     1,
	}

	// Mock SubscribeTopics
	mockConsumer.On("SubscribeTopics", []string{"test-topic"}, mock.AnythingOfType("kafka.RebalanceCb")).Return(nil)

	// Create a test message
	testWrapper := PostHogEventWrapper{
		Uuid:       "test-uuid",
		DistinctId: "test-distinct-id",
		Ip:         "192.0.2.1",
		Data:       `{"event": "test-event", "properties": {"token": "test-token"}}`,
	}
	testMessageValue, _ := json.Marshal(testWrapper)
	testMessage := &kafka.Message{
		Value: testMessageValue,
	}

	// Mock ReadMessage
	mockConsumer.On("ReadMessage", mock.AnythingOfType("time.Duration")).Return(testMessage, nil).Maybe()

	// Mock GeoLocator Lookup
	mockGeoLocator.On("Lookup", "192.0.2.1").Return(geo.GeoLookupResult{Latitude: 37.7749, Longitude: -122.4194, CountryCode: "US"}, nil)

	// Run Consume in a goroutine
	go consumer.Consume()

	// Wait for the message to be processed
	select {
	case event := <-outgoingChan:
		assert.Equal(t, "test-uuid", event.Uuid)
		assert.Equal(t, "test-distinct-id", event.DistinctId)
		assert.Equal(t, "test-event", event.Event)
		assert.Equal(t, "test-token", event.Token)
		assert.Equal(t, 37.7749, event.Lat)
		assert.Equal(t, -122.4194, event.Lng)
	case <-time.After(time.Second):
		t.Fatal("Timed out waiting for message")
	}

	// Check if the message was also sent to statsChan
	select {
	case <-statsChan:
		// Message received in statsChan
	case <-time.After(time.Second):
		t.Fatal("Timed out waiting for stats message")
	}

	// Test error handling
	mockConsumer.On("ReadMessage", mock.AnythingOfType("time.Duration")).Return(nil, errors.New("read error")).Maybe()
	time.Sleep(time.Millisecond * 100) // Give some time for the error to be processed

	// Assert that all expectations were met
	mockConsumer.AssertExpectations(t)
	mockGeoLocator.AssertExpectations(t)
}

func TestPostHogKafkaConsumer_Close(t *testing.T) {
	mockConsumer := new(mocks.KafkaConsumerInterface)
	consumer := &PostHogKafkaConsumer{
		consumer: mockConsumer,
		incoming: make(chan []byte),
	}

	mockConsumer.On("Close").Return(nil)

	consumer.Close()

	mockConsumer.AssertExpectations(t)
}

func TestParse(t *testing.T) {
	mockGeoLocator := new(mocks.GeoLocator)
	mockGeoLocator.On("Lookup", "127.0.0.1").
		Return(geo.GeoLookupResult{Latitude: 10., Longitude: 20., CountryCode: "US"}, nil).Once()
	data, err := os.ReadFile("testdata/event.json")
	assert.NoError(t, err)
	got := parse(mockGeoLocator, data)
	assert.Equal(t, PostHogEvent{
		Token:     "this is token",
		Timestamp: 1738073128810.,
		Event:     "consumer_ack",
		Properties: map[string]interface{}{
			"$groups": map[string]interface{}{
				"account": "757eb2c3-7343-4e92-b040-a1d0201b54e6",
			},
			"consumer_id":   "67dc0ac7-c9ec-4f8a-8cad-0fbb3695c86c",
			"consumer_name": "backend_task_sink",
			"event_count":   6.,
			"message_count": 0.,
			"message_kind":  "event",
		},
		Lat:         10,
		Lng:         20,
		CountryCode: "US",
	}, got)
}

func TestFlexibleString_UnmarshalJSON(t *testing.T) {
	tests := []struct {
		name     string
		input    string
		expected string
	}{
		{
			name:     "string value",
			input:    `"user123"`,
			expected: "user123",
		},
		{
			name:     "integer value",
			input:    `21`,
			expected: "21",
		},
		{
			name:     "large integer value",
			input:    `1234567890`,
			expected: "1234567890",
		},
		{
			name:     "float value",
			input:    `123.456`,
			expected: "123.456",
		},
		{
			name:     "null value",
			input:    `null`,
			expected: "",
		},
		{
			name:     "empty string",
			input:    `""`,
			expected: "",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var f FlexibleString
			err := json.Unmarshal([]byte(tt.input), &f)
			assert.NoError(t, err)
			assert.Equal(t, tt.expected, string(f))
		})
	}
}

func TestPostHogEventWrapper_NumericDistinctId(t *testing.T) {
	tests := []struct {
		name               string
		jsonInput          string
		expectedDistinctId string
	}{
		{
			name:               "string distinct_id",
			jsonInput:          `{"uuid":"abc","distinct_id":"user123","ip":"","data":"","token":""}`,
			expectedDistinctId: "user123",
		},
		{
			name:               "numeric distinct_id",
			jsonInput:          `{"uuid":"abc","distinct_id":21,"ip":"","data":"","token":""}`,
			expectedDistinctId: "21",
		},
		{
			name:               "large numeric distinct_id",
			jsonInput:          `{"uuid":"abc","distinct_id":1234567890,"ip":"","data":"","token":""}`,
			expectedDistinctId: "1234567890",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var wrapper PostHogEventWrapper
			err := json.Unmarshal([]byte(tt.jsonInput), &wrapper)
			assert.NoError(t, err)
			assert.Equal(t, tt.expectedDistinctId, string(wrapper.DistinctId))
		})
	}
}

func TestParse_NumericDistinctId(t *testing.T) {
	mockGeoLocator := new(mocks.GeoLocator)

	// Test that numeric distinct_id from posthog-ruby SDK is handled correctly
	// This is the exact format that was causing "parse error: expected string near offset 17 of '21'"
	// The wrapper has distinct_id at the top level, and the data field contains the inner event JSON
	input := `{"distinct_id":21,"uuid":"test-uuid","ip":"","data":"{\"event\":\"$pageview\",\"properties\":{\"$lib\":\"posthog-ruby\"}}","token":"test-token"}`

	got := parse(mockGeoLocator, []byte(input))

	assert.Equal(t, "21", got.DistinctId)
	assert.Equal(t, "$pageview", got.Event)
	assert.Equal(t, "test-token", got.Token)
}

func TestParse_WrapperTimestampFallback(t *testing.T) {
	mockGeoLocator := new(mocks.GeoLocator)

	input := `{"distinct_id":"user-123","uuid":"test-uuid","ip":"","data":"{\"event\":\"$pageview\",\"properties\":{}}","token":"test-token","timestamp":"2026-01-09T21:00:00.000Z"}`

	got := parse(mockGeoLocator, []byte(input))

	assert.Equal(t, "2026-01-09T21:00:00.000Z", got.Timestamp)
	assert.Equal(t, "$pageview", got.Event)
}

func TestParse_InnerTimestampOverridesWrapper(t *testing.T) {
	mockGeoLocator := new(mocks.GeoLocator)

	input := `{"distinct_id":"user-123","uuid":"test-uuid","ip":"","data":"{\"event\":\"$pageview\",\"properties\":{},\"timestamp\":\"2026-01-09T02:00:00.000Z\"}","token":"test-token","timestamp":"2026-01-10T21:00:00.000Z"}`

	got := parse(mockGeoLocator, []byte(input))

	assert.Equal(t, "2026-01-09T02:00:00.000Z", got.Timestamp)
	assert.Equal(t, "$pageview", got.Event)
}
