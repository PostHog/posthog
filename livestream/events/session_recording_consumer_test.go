package events

import (
	"testing"

	"github.com/confluentinc/confluent-kafka-go/v2/kafka"
	"github.com/stretchr/testify/assert"
)

func TestParseSessionRecordingHeaders(t *testing.T) {
	tests := []struct {
		name       string
		headers    []kafka.Header
		wantToken  string
		wantSessId string
	}{
		{
			name:       "empty headers",
			headers:    nil,
			wantToken:  "",
			wantSessId: "",
		},
		{
			name:       "empty headers slice",
			headers:    []kafka.Header{},
			wantToken:  "",
			wantSessId: "",
		},
		{
			name: "token only",
			headers: []kafka.Header{
				{Key: "token", Value: []byte("tok1")},
			},
			wantToken:  "tok1",
			wantSessId: "",
		},
		{
			name: "session_id only",
			headers: []kafka.Header{
				{Key: "session_id", Value: []byte("sess1")},
			},
			wantToken:  "",
			wantSessId: "sess1",
		},
		{
			name: "both present",
			headers: []kafka.Header{
				{Key: "token", Value: []byte("tok1")},
				{Key: "session_id", Value: []byte("sess1")},
			},
			wantToken:  "tok1",
			wantSessId: "sess1",
		},
		{
			name: "both present reversed order",
			headers: []kafka.Header{
				{Key: "session_id", Value: []byte("sess1")},
				{Key: "token", Value: []byte("tok1")},
			},
			wantToken:  "tok1",
			wantSessId: "sess1",
		},
		{
			name: "with extra headers",
			headers: []kafka.Header{
				{Key: "distinct_id", Value: []byte("user123")},
				{Key: "token", Value: []byte("tok1")},
				{Key: "timestamp", Value: []byte("12345")},
				{Key: "session_id", Value: []byte("sess1")},
			},
			wantToken:  "tok1",
			wantSessId: "sess1",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			gotToken, gotSessId := parseSessionRecordingHeaders(tt.headers)
			assert.Equal(t, tt.wantToken, gotToken)
			assert.Equal(t, tt.wantSessId, gotSessId)
		})
	}
}
