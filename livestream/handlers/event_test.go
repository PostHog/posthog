package handlers

import (
	"net/http/httptest"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestEventWriteTo(t *testing.T) {
	tests := []struct {
		name     string
		event    Event
		expected string
	}{
		{
			name: "Full event",
			event: Event{
				ID:    []byte("1"),
				Data:  []byte("test data"),
				Event: []byte("message"),
				Retry: []byte("3000"),
			},
			expected: "id: 1\ndata: test data\nevent: message\nretry: 3000\n\n",
		},
		{
			name: "Event with multiline data",
			event: Event{
				ID:   []byte("2"),
				Data: []byte("line1\nline2\nline3"),
			},
			expected: "id: 2\ndata: line1\ndata: line2\ndata: line3\n\n",
		},
		{
			name: "Event with comment only",
			event: Event{
				Comment: []byte("This is a comment"),
			},
			expected: ": This is a comment\n\n",
		},
		{
			name:     "Empty event",
			event:    Event{},
			expected: "",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			w := httptest.NewRecorder()
			err := tt.event.WriteTo(w)

			require.NoError(t, err, "WriteTo() should not return an error")
			assert.Equal(t, tt.expected, w.Body.String(), "WriteTo() output should match expected")
		})
	}
}
