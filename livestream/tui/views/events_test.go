package views

import (
	"testing"
	"time"

	"github.com/posthog/posthog/livestream/tui/sse"
	"github.com/stretchr/testify/assert"
)

func TestEventsView_AddEvent(t *testing.T) {
	v := NewEventsView()
	assert.Equal(t, 0, v.EventCount())

	v.AddEvent(sse.EventMsg{Event: "$pageview", ReceivedAt: time.Now()})
	assert.Equal(t, 1, v.EventCount())
}

func TestEventsView_CircularBuffer(t *testing.T) {
	v := NewEventsView()
	v.SetSize(80, 20)

	for i := 0; i < maxEvents+50; i++ {
		v.AddEvent(sse.EventMsg{Event: "$pageview", ReceivedAt: time.Now()})
	}

	assert.Equal(t, maxEvents, v.EventCount())
}

func TestEventsView_Pause(t *testing.T) {
	v := NewEventsView()
	v.SetPaused(true)

	v.AddEvent(sse.EventMsg{Event: "$pageview", ReceivedAt: time.Now()})
	assert.Equal(t, 0, v.EventCount())

	v.SetPaused(false)
	v.AddEvent(sse.EventMsg{Event: "$pageview", ReceivedAt: time.Now()})
	assert.Equal(t, 1, v.EventCount())
}

func TestEventsView_Clear(t *testing.T) {
	v := NewEventsView()
	v.AddEvent(sse.EventMsg{Event: "$pageview", ReceivedAt: time.Now()})
	v.AddEvent(sse.EventMsg{Event: "$identify", ReceivedAt: time.Now()})
	assert.Equal(t, 2, v.EventCount())

	v.Clear()
	assert.Equal(t, 0, v.EventCount())
}

func TestEventsView_Navigation(t *testing.T) {
	v := NewEventsView()
	v.SetSize(80, 20)

	v.AddEvent(sse.EventMsg{Event: "event1", ReceivedAt: time.Now()})
	v.AddEvent(sse.EventMsg{Event: "event2", ReceivedAt: time.Now()})
	v.AddEvent(sse.EventMsg{Event: "event3", ReceivedAt: time.Now()})

	v.MoveUp()
	v.MoveUp()

	idx := v.Select()
	assert.GreaterOrEqual(t, idx, 0)

	e := v.SelectedEvent()
	assert.NotNil(t, e)

	v.Deselect()
	assert.Nil(t, v.SelectedEvent())
}

func TestTruncate(t *testing.T) {
	tests := []struct {
		name     string
		input    string
		maxLen   int
		expected string
	}{
		{"short string", "hello", 10, "hello"},
		{"exact length", "hello", 5, "hello"},
		{"needs truncation", "hello world", 8, "hello..."},
		{"very short max", "hello", 2, "he"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.expected, truncate(tt.input, tt.maxLen))
		})
	}
}

func TestRelativeTime(t *testing.T) {
	assert.Equal(t, "now", relativeTime(time.Now()))
	assert.Contains(t, relativeTime(time.Now().Add(-30*time.Second)), "s ago")
	assert.Contains(t, relativeTime(time.Now().Add(-5*time.Minute)), "m ago")
	assert.Contains(t, relativeTime(time.Now().Add(-2*time.Hour)), "h ago")
}
