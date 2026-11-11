package events

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"testing"
	"time"

	"github.com/confluentinc/confluent-kafka-go/v2/kafka"
	"github.com/posthog/posthog/livestream/bot"
	"github.com/posthog/posthog/livestream/configs"
	"github.com/posthog/posthog/livestream/geo"
	"github.com/posthog/posthog/livestream/mocks"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/mock"
	"github.com/stretchr/testify/require"
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
		incoming:     make(chan incomingMessage),
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
	go consumer.Consume(context.Background())

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
		incoming: make(chan incomingMessage),
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
	got := parse(mockGeoLocator, nil, data)
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

	got := parse(mockGeoLocator, nil, []byte(input))

	assert.Equal(t, "21", got.DistinctId)
	assert.Equal(t, "$pageview", got.Event)
	assert.Equal(t, "test-token", got.Token)
}

func TestParse_WrapperTimestampFallback(t *testing.T) {
	mockGeoLocator := new(mocks.GeoLocator)

	input := `{"distinct_id":"user-123","uuid":"test-uuid","ip":"","data":"{\"event\":\"$pageview\",\"properties\":{}}","token":"test-token","timestamp":"2026-01-09T21:00:00.000Z"}`

	got := parse(mockGeoLocator, nil, []byte(input))

	assert.Equal(t, "2026-01-09T21:00:00.000Z", got.Timestamp)
	assert.Equal(t, "$pageview", got.Event)
}

func TestParse_InnerTimestampOverridesWrapper(t *testing.T) {
	mockGeoLocator := new(mocks.GeoLocator)

	input := `{"distinct_id":"user-123","uuid":"test-uuid","ip":"","data":"{\"event\":\"$pageview\",\"properties\":{},\"timestamp\":\"2026-01-09T02:00:00.000Z\"}","token":"test-token","timestamp":"2026-01-10T21:00:00.000Z"}`

	got := parse(mockGeoLocator, nil, []byte(input))

	assert.Equal(t, "2026-01-09T02:00:00.000Z", got.Timestamp)
	assert.Equal(t, "$pageview", got.Event)
}

func TestParse_CaptureOptions(t *testing.T) {
	tests := []struct {
		name     string
		data     string
		options  string
		expected map[string]interface{}
	}{
		{
			name: "options override client properties",
			data: `{"event":"$pageview","properties":{"$session_id":"client","$window_id":"client","$cookieless_mode":false,` +
				`"$ignore_sent_at":true,"$product_tour_id":"client","$process_person_profile":true}}`,
			options: `{"session_id":"server","window_id":"","cookieless_mode":true,"disable_skew_correction":false,` +
				`"product_tour_id":"server","process_person_profile":false}`,
			expected: map[string]interface{}{
				"$session_id": "server", "$window_id": "", "$cookieless_mode": true,
				"$ignore_sent_at": false, "$product_tour_id": "server", "$process_person_profile": false,
			},
		},
		{
			name:     "values with the wrong type are skipped",
			data:     `{"event":"$pageview","properties":{"$session_id":"client","$cookieless_mode":false}}`,
			options:  `{"session_id":42,"cookieless_mode":"true","window_id":null,"req_lib":"posthog-go"}`,
			expected: map[string]interface{}{"$session_id": "client", "$cookieless_mode": false},
		},
		{
			name:     "req_lib fills a missing $lib",
			data:     `{"event":"$pageview","properties":{}}`,
			options:  `{"req_lib":"posthog-go","req_lib_version":"2.0.0"}`,
			expected: map[string]interface{}{"$lib": "posthog-go", "$lib_version": "2.0.0"},
		},
		{
			name:     "req_lib fills a null $lib",
			data:     `{"event":"$pageview","properties":{"$lib":null,"$lib_version":"0.9.0"}}`,
			options:  `{"req_lib":"posthog-go","req_lib_version":"2.0.0"}`,
			expected: map[string]interface{}{"$lib": "posthog-go", "$lib_version": "2.0.0"},
		},
		{
			name:     "a client $lib wins over req_lib",
			data:     `{"event":"$pageview","properties":{"$lib":"posthog-go-mcp","$lib_version":"0.3.0"}}`,
			options:  `{"req_lib":"posthog-go","req_lib_version":"2.0.0"}`,
			expected: map[string]interface{}{"$lib": "posthog-go-mcp", "$lib_version": "0.3.0"},
		},
		{
			name:     "a bool for a string option is skipped",
			data:     `{"event":"$pageview","properties":{"$session_id":"client","$product_tour_id":"client"}}`,
			options:  `{"session_id":true,"product_tour_id":false}`,
			expected: map[string]interface{}{"$session_id": "client", "$product_tour_id": "client"},
		},
		{
			name:     "req_lib fills a missing $lib_version when $lib matches",
			data:     `{"event":"$pageview","properties":{"$lib":"posthog-go"}}`,
			options:  `{"req_lib":"posthog-go","req_lib_version":"2.0.0"}`,
			expected: map[string]interface{}{"$lib": "posthog-go", "$lib_version": "2.0.0"},
		},
		{
			name:     "req_lib fills a null $lib_version when $lib matches",
			data:     `{"event":"$pageview","properties":{"$lib":"posthog-go","$lib_version":null}}`,
			options:  `{"req_lib":"posthog-go","req_lib_version":"2.0.0"}`,
			expected: map[string]interface{}{"$lib": "posthog-go", "$lib_version": "2.0.0"},
		},
		{
			name:     "a client $lib_version for the same $lib is kept",
			data:     `{"event":"$pageview","properties":{"$lib":"posthog-go","$lib_version":"1.9.0"}}`,
			options:  `{"req_lib":"posthog-go","req_lib_version":"2.0.0"}`,
			expected: map[string]interface{}{"$lib": "posthog-go", "$lib_version": "1.9.0"},
		},
		{
			name:     "req_lib fills an empty $lib",
			data:     `{"event":"$pageview","properties":{"$lib":""}}`,
			options:  `{"req_lib":"posthog-go","req_lib_version":"2.0.0"}`,
			expected: map[string]interface{}{"$lib": "posthog-go", "$lib_version": "2.0.0"},
		},
		{
			name:     "req_lib fills a non-string $lib",
			data:     `{"event":"$pageview","properties":{"$lib":5,"$lib_version":"0.9.0"}}`,
			options:  `{"req_lib":"posthog-go","req_lib_version":"2.0.0"}`,
			expected: map[string]interface{}{"$lib": "posthog-go", "$lib_version": "2.0.0"},
		},
		{
			name:     "req_lib fills an empty or non-string $lib_version when $lib matches",
			data:     `{"event":"$pageview","properties":{"$lib":"posthog-go","$lib_version":1}}`,
			options:  `{"req_lib":"posthog-go","req_lib_version":"2.0.0"}`,
			expected: map[string]interface{}{"$lib": "posthog-go", "$lib_version": "2.0.0"},
		},
		{
			name:     "a client $lib keeps an empty $lib_version",
			data:     `{"event":"$pageview","properties":{"$lib":"custom","$lib_version":""}}`,
			options:  `{"req_lib":"posthog-go","req_lib_version":"2.0.0"}`,
			expected: map[string]interface{}{"$lib": "custom", "$lib_version": ""},
		},
		{
			name:     "a whitespace $lib is kept",
			data:     `{"event":"$pageview","properties":{"$lib":" "}}`,
			options:  `{"req_lib":"posthog-go","req_lib_version":"2.0.0"}`,
			expected: map[string]interface{}{"$lib": " "},
		},
		{
			name:     "a whitespace $lib_version for the same $lib is kept",
			data:     `{"event":"$pageview","properties":{"$lib":"posthog-go","$lib_version":" "}}`,
			options:  `{"req_lib":"posthog-go","req_lib_version":"2.0.0"}`,
			expected: map[string]interface{}{"$lib": "posthog-go", "$lib_version": " "},
		},
		{
			name:     "req_lib fills an array $lib",
			data:     `{"event":"$pageview","properties":{"$lib":["posthog-go"]}}`,
			options:  `{"req_lib":"posthog-go","req_lib_version":"2.0.0"}`,
			expected: map[string]interface{}{"$lib": "posthog-go", "$lib_version": "2.0.0"},
		},
		{
			name:     "an empty req_lib is skipped",
			data:     `{"event":"$pageview","properties":{"$lib_version":"0.9.0"}}`,
			options:  `{"req_lib":"","req_lib_version":"2.0.0"}`,
			expected: map[string]interface{}{"$lib_version": "0.9.0"},
		},
		{
			name:     "a whitespace req_lib is skipped",
			data:     `{"event":"$pageview","properties":{"$lib_version":"0.9.0"}}`,
			options:  `{"req_lib":" ","req_lib_version":"2.0.0"}`,
			expected: map[string]interface{}{"$lib_version": "0.9.0"},
		},
		{
			name:     "an empty req_lib_version is skipped",
			data:     `{"event":"$pageview","properties":{"$lib_version":"0.9.0"}}`,
			options:  `{"req_lib":"posthog-go","req_lib_version":""}`,
			expected: map[string]interface{}{"$lib_version": "0.9.0"},
		},
		{
			name:     "a whitespace req_lib_version is skipped",
			data:     `{"event":"$pageview","properties":{"$lib_version":"0.9.0"}}`,
			options:  `{"req_lib":"posthog-go","req_lib_version":"\t"}`,
			expected: map[string]interface{}{"$lib_version": "0.9.0"},
		},
		{
			name: "capture spliced bytes with duplicate keys read as the server values",
			data: `{"event":"$pageview","properties":{"$lib":"client-lib","$session_id":"client-session",` +
				`"$session_id":"server-session","$process_person_profile":false,"$lib":"posthog-go","$lib_version":"2.0.0"}}`,
			options: `{"session_id":"server-session","process_person_profile":false,"req_lib":"posthog-go","req_lib_version":"2.0.0"}`,
			expected: map[string]interface{}{
				"$session_id": "server-session", "$process_person_profile": false,
				"$lib": "posthog-go", "$lib_version": "2.0.0",
			},
		},
		{
			name:     "req_lib_version without req_lib is skipped",
			data:     `{"event":"$pageview","properties":{"a":1}}`,
			options:  `{"req_lib_version":"2.0.0"}`,
			expected: map[string]interface{}{"a": float64(1)},
		},
		{
			name:     "unknown option keys stay out of the properties",
			data:     `{"event":"$pageview","properties":{"a":1}}`,
			options:  `{"future_key":"x","session_id":"server"}`,
			expected: map[string]interface{}{"a": float64(1), "$session_id": "server"},
		},
		{
			name:     "options apply to empty properties",
			data:     `{"event":"$pageview","properties":{}}`,
			options:  `{"session_id":"server"}`,
			expected: map[string]interface{}{"$session_id": "server"},
		},
		{
			name:     "options inside data are ignored",
			data:     `{"event":"$pageview","properties":{"$session_id":"client"},"options":{"session_id":"injected","req_lib":"x","req_lib_version":"1"}}`,
			expected: map[string]interface{}{"$session_id": "client"},
		},
		{
			name:     "options apply to null properties",
			data:     `{"event":"$pageview","properties":null}`,
			options:  `{"session_id":"server"}`,
			expected: map[string]interface{}{"$session_id": "server"},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			wrapper := map[string]interface{}{"uuid": "test-uuid", "distinct_id": "user-1", "data": tt.data, "token": "tok"}
			if tt.options != "" {
				wrapper["options"] = json.RawMessage(tt.options)
			}
			input, err := json.Marshal(wrapper)
			require.NoError(t, err)

			got := parse(new(mocks.GeoLocator), nil, input)

			assert.Equal(t, tt.expected, got.Properties)
		})
	}
}

func TestPostHogEventWrapper_KeepsEveryOptionKey(t *testing.T) {
	var wrapper PostHogEventWrapper
	require.NoError(t, json.Unmarshal([]byte(`{"options":{"session_id":"s","future_key":{"nested":[1,true]}}}`), &wrapper))

	assert.Equal(t, CaptureOptions{
		"session_id": "s",
		"future_key": map[string]interface{}{"nested": []interface{}{float64(1), true}},
	}, wrapper.Options)
}

func TestParse_NonObjectOptionsKeepTheRestOfTheMessage(t *testing.T) {
	for _, options := range []string{`"session_id"`, `["session_id"]`, `42`, `true`, `null`} {
		t.Run(options, func(t *testing.T) {
			input := `{"uuid":"test-uuid","options":` + options + `,"distinct_id":"user-1",` +
				`"data":"{\"event\":\"$pageview\",\"properties\":{\"$session_id\":\"client\"}}","token":"tok"}`

			got := parse(new(mocks.GeoLocator), nil, []byte(input))

			assert.Equal(t, "$pageview", got.Event)
			assert.Equal(t, "tok", got.Token)
			assert.Equal(t, "user-1", got.DistinctId)
			assert.Equal(t, map[string]interface{}{"$session_id": "client"}, got.Properties)
		})
	}
}

func TestParse_OptionSessionIdReachesFiltersAndResponse(t *testing.T) {
	input := `{"uuid":"test-uuid","distinct_id":"user-1","token":"tok","options":{"session_id":"server"},` +
		`"data":"{\"event\":\"$pageview\",\"properties\":{\"$session_id\":\"client\"}}"}`

	event := parse(new(mocks.GeoLocator), nil, []byte(input))

	assert.True(t, matchesPropertyFilters(event.Properties,
		[]CompiledPropertyFilter{NewCompiledPropertyFilter("$session_id", OpExact, []string{"server"})}))
	response := convertToResponsePostHogEvent(event, 1, []string{"$session_id"}, nil)
	assert.Equal(t, map[string]interface{}{"$session_id": "server"}, response.Properties)
}

func TestRunParsing_SubscriberGate(t *testing.T) {
	watchedBody := `{"distinct_id":"user-1","uuid":"uuid-1","ip":"","data":"{\"event\":\"$pageview\",\"properties\":{}}","token":"tok"}`

	tests := []struct {
		name          string
		in            incomingMessage
		withBroker    bool
		gate          PublishGate
		wantStats     CountEvent
		wantPublished bool
	}{
		{
			name:       "unwatched token is counted from headers without parsing",
			in:         incomingMessage{value: []byte("not json"), token: "tok", distinctID: "user-1"},
			withBroker: true,
			gate:       fakeGate{def: false},
			wantStats:  CountEvent{Token: "tok", DistinctID: "user-1"},
		},
		{
			name:          "watched token is parsed and published",
			in:            incomingMessage{value: []byte(watchedBody), token: "tok", distinctID: "user-1"},
			withBroker:    true,
			gate:          fakeGate{def: true},
			wantStats:     CountEvent{Token: "tok", DistinctID: "user-1"},
			wantPublished: true,
		},
		{
			name:       "missing headers fall back to parsing the body",
			in:         incomingMessage{value: []byte(watchedBody)},
			withBroker: true,
			gate:       fakeGate{def: false},
			wantStats:  CountEvent{Token: "tok", DistinctID: "user-1"},
		},
		{
			name:          "no gate parses and publishes every event",
			in:            incomingMessage{value: []byte(watchedBody), token: "tok", distinctID: "user-1"},
			withBroker:    true,
			wantStats:     CountEvent{Token: "tok", DistinctID: "user-1"},
			wantPublished: true,
		},
		{
			name:      "in-memory mode parses every event",
			in:        incomingMessage{value: []byte(watchedBody), token: "tok", distinctID: "user-1"},
			wantStats: CountEvent{Token: "tok", DistinctID: "user-1"},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			consumer := &PostHogKafkaConsumer{
				incoming:     make(chan incomingMessage, 1),
				outgoingChan: make(chan PostHogEvent, 1),
				statsChan:    make(chan CountEvent, 1),
			}
			if tt.withBroker {
				consumer.Broker = NewRedisEventBrokerFromClient(nil, 1, 1)
				if tt.gate != nil {
					consumer.Broker.SetPublishGate(tt.gate)
				}
			}

			consumer.incoming <- tt.in
			close(consumer.incoming)
			consumer.runParsing(context.Background())

			require.Len(t, consumer.statsChan, 1)
			assert.Equal(t, tt.wantStats, <-consumer.statsChan)
			if tt.withBroker {
				if tt.wantPublished {
					require.Len(t, consumer.Broker.publishCh, 1)
					assert.Equal(t, "$pageview", (<-consumer.Broker.publishCh).Event)
				} else {
					assert.Empty(t, consumer.Broker.publishCh)
				}
			} else {
				require.Len(t, consumer.outgoingChan, 1)
				assert.Equal(t, "$pageview", (<-consumer.outgoingChan).Event)
			}
		})
	}
}

func BenchmarkRunParsingPerEvent(b *testing.B) {
	properties := map[string]any{
		"$current_url":                   "https://www.example.com/pricing?plan=team&utm_source=newsletter",
		"$pathname":                      "/pricing",
		"$host":                          "www.example.com",
		"$referrer":                      "https://search.example.org/",
		"$referring_domain":              "search.example.org",
		"$browser":                       "Chrome",
		"$browser_version":               141,
		"$os":                            "Mac OS X",
		"$os_version":                    "15.6.0",
		"$device_type":                   "Desktop",
		"$device_id":                     "019a0000-0000-7000-8000-000000000001",
		"$session_id":                    "019a0000-0000-7000-8000-000000000002",
		"$window_id":                     "019a0000-0000-7000-8000-000000000003",
		"$pageview_id":                   "019a0000-0000-7000-8000-000000000004",
		"$lib":                           "web",
		"$lib_version":                   "1.280.0",
		"$screen_height":                 1117,
		"$screen_width":                  1728,
		"$viewport_height":               982,
		"$viewport_width":                1728,
		"$raw_user_agent":                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
		"$timezone":                      "America/New_York",
		"$timezone_offset":               240,
		"$is_identified":                 false,
		"$process_person_profile":        true,
		"$configured_session_timeout_ms": 1800000,
		"$sdk_debug_retry_queue_size":    0,
		"$recording_status":              "active",
		"$replay_script_config":          nil,
		"$active_feature_flags":          []string{"new-pricing-page", "checkout-v2"},
		"$feature/new-pricing-page":      true,
		"$feature/checkout-v2":           "test",
		"utm_source":                     "newsletter",
		"title":                          "Pricing - Example",
		"$ip":                            "",
		"token":                          "tok",
		"distinct_id":                    "019a0000-0000-7000-8000-000000000001",
	}
	data, err := json.Marshal(map[string]any{
		"event":      "$pageview",
		"properties": properties,
		"timestamp":  "2026-10-05T12:00:00.000Z",
	})
	if err != nil {
		b.Fatal(err)
	}
	value, err := json.Marshal(PostHogEventWrapper{
		Uuid:       "019a0000-0000-7000-8000-000000000005",
		DistinctId: "019a0000-0000-7000-8000-000000000001",
		Data:       string(data),
		Token:      "tok",
		Timestamp:  "2026-10-05T12:00:00.000Z",
	})
	if err != nil {
		b.Fatal(err)
	}
	msg := &kafka.Message{
		Value: value,
		Headers: []kafka.Header{
			{Key: "token", Value: []byte("tok")},
			{Key: "distinct_id", Value: []byte("019a0000-0000-7000-8000-000000000001")},
			{Key: "event", Value: []byte("$pageview")},
		},
	}
	valueWithOptions, err := json.Marshal(map[string]any{
		"uuid":        "019a0000-0000-7000-8000-000000000005",
		"distinct_id": "019a0000-0000-7000-8000-000000000001",
		"data":        string(data),
		"token":       "tok",
		"timestamp":   "2026-10-05T12:00:00.000Z",
		"options": map[string]any{
			"session_id":             "019a0000-0000-7000-8000-000000000002",
			"window_id":              "019a0000-0000-7000-8000-000000000003",
			"process_person_profile": true,
			"req_lib":                "posthog-go",
			"req_lib_version":        "1.6.0",
		},
	})
	if err != nil {
		b.Fatal(err)
	}
	classifier := bot.NewClassifier()

	b.Run("full parse", func(b *testing.B) {
		b.ReportAllocs()
		for b.Loop() {
			parse(nil, classifier, newIncomingMessage(msg).value)
		}
	})
	b.Run("full parse with options", func(b *testing.B) {
		b.ReportAllocs()
		for b.Loop() {
			parse(nil, classifier, valueWithOptions)
		}
	})
	b.Run("headers only", func(b *testing.B) {
		b.ReportAllocs()
		for b.Loop() {
			newIncomingMessage(msg)
		}
	})
}

func TestSplitTopics(t *testing.T) {
	tests := []struct {
		name     string
		input    string
		expected []string
	}{
		{
			name:     "single topic",
			input:    "events_topic",
			expected: []string{"events_topic"},
		},
		{
			name:     "two topics",
			input:    "topic-1,topic-2",
			expected: []string{"topic-1", "topic-2"},
		},
		{
			name:     "surrounding whitespace",
			input:    " a , b ",
			expected: []string{"a", "b"},
		},
		{
			name:     "empty and trailing segments",
			input:    "a,,b,",
			expected: []string{"a", "b"},
		},
		{
			name:     "empty string",
			input:    "",
			expected: []string{},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.expected, splitTopics(tt.input))
		})
	}
}

func TestApplyKafkaConfigOverrides_ClientRack(t *testing.T) {
	// A non-empty ClientRack sets client.rack (KIP-392 same-AZ fetch).
	cfg := &kafka.ConfigMap{}
	applyKafkaConfigOverrides(cfg, configs.ConsumerConfig{ClientRack: "use1-az2"})
	v, err := cfg.Get("client.rack", nil)
	assert.NoError(t, err)
	assert.Equal(t, "use1-az2", v)

	// An empty ClientRack leaves client.rack unset (librdkafka default).
	empty := &kafka.ConfigMap{}
	applyKafkaConfigOverrides(empty, configs.ConsumerConfig{})
	ev, err := empty.Get("client.rack", nil)
	assert.NoError(t, err)
	assert.Nil(t, ev)
}
