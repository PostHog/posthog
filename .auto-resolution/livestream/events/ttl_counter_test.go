package events

import (
	"sync"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestNewSlidingWindowCounter(t *testing.T) {
	windowSize := time.Minute
	swc := NewSlidingWindowCounter(windowSize)

	assert.Equal(t, windowSize, swc.windowSize, "Window size should match")
	assert.Empty(t, swc.events, "Events slice should be empty")
}

func TestIncrement(t *testing.T) {
	swc := NewSlidingWindowCounter(time.Minute)

	swc.Increment()
	assert.Equal(t, 1, swc.Count(), "Count should be 1 after first increment")

	swc.Increment()
	assert.Equal(t, 2, swc.Count(), "Count should be 2 after second increment")
}

func TestCount(t *testing.T) {
	swc := NewSlidingWindowCounter(time.Second)

	swc.Increment()
	time.Sleep(500 * time.Millisecond)
	swc.Increment()

	assert.Equal(t, 2, swc.Count(), "Count should be 2 within the time window")

	time.Sleep(600 * time.Millisecond)

	assert.Equal(t, 1, swc.Count(), "Count should be 1 after oldest event expires")
}

func TestRemoveOldEvents(t *testing.T) {
	swc := NewSlidingWindowCounter(time.Second)

	now := time.Now()
	swc.events = []time.Time{
		now.Add(-2 * time.Second),
		now.Add(-1500 * time.Millisecond),
		now.Add(-500 * time.Millisecond),
		now,
	}

	swc.removeOldEvents(now)

	require.Len(t, swc.events, 2, "Should have 2 events after removal")
	assert.Equal(t, now.Add(-500*time.Millisecond), swc.events[0], "First event should be 500ms ago")
	assert.Equal(t, now, swc.events[1], "Second event should be now")
}

func TestConcurrency(t *testing.T) {
	swc := NewSlidingWindowCounter(time.Minute)
	iterations := 1000
	var wg sync.WaitGroup

	wg.Add(iterations)
	for i := 0; i < iterations; i++ {
		go func() {
			defer wg.Done()
			swc.Increment()
		}()
	}

	wg.Wait()

	assert.Equal(t, iterations, swc.Count(), "Count should match the number of increments")
}
