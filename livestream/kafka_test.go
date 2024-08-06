package main

import (
	"encoding/json"
	"errors"
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
	statsChan := make(chan PostHogEvent, 1)

	// Create PostHogKafkaConsumer
	consumer := &PostHogKafkaConsumer{
		consumer:     mockConsumer,
		topic:        "test-topic",
		geolocator:   mockGeoLocator,
		outgoingChan: outgoingChan,
		statsChan:    statsChan,
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
	}

	mockConsumer.On("Close").Return(nil)

	consumer.Close()

	mockConsumer.AssertExpectations(t)
}
