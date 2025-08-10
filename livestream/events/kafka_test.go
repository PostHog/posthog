package events

import (
	"encoding/json"
	"errors"
	"os"
	"testing"
	"time"

	"github.com/confluentinc/confluent-kafka-go/v2/kafka"
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
	mockGeoLocator.On("Lookup", "192.0.2.1").Return(37.7749, -122.4194, nil)

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
		Return(10., 20., nil).Once()
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
		Lat: 10,
		Lng: 20,
	}, got)
}
