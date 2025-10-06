package events

import (
	"sync"
	"time"
)

type SlidingWindowCounter struct {
	mu         sync.Mutex
	events     []time.Time
	windowSize time.Duration
}

func NewSlidingWindowCounter(windowSize time.Duration) *SlidingWindowCounter {
	swc := &SlidingWindowCounter{
		events:     make([]time.Time, 0),
		windowSize: windowSize,
	}

	// Start a goroutine to periodically remove old events
	go func() {
		ticker := time.NewTicker(time.Second)
		defer ticker.Stop()

		for range ticker.C {
			swc.mu.Lock()
			swc.removeOldEvents(time.Now())
			swc.mu.Unlock()
		}
	}()

	return swc
}

func (swc *SlidingWindowCounter) Increment() {
	swc.mu.Lock()
	defer swc.mu.Unlock()

	now := time.Now()
	swc.events = append(swc.events, now)
}

func (swc *SlidingWindowCounter) Count() int {
	swc.mu.Lock()
	defer swc.mu.Unlock()

	now := time.Now()
	swc.removeOldEvents(now)
	return len(swc.events)
}

func (swc *SlidingWindowCounter) removeOldEvents(now time.Time) {
	cutoff := now.Add(-swc.windowSize)
	i := 0
	for ; i < len(swc.events); i++ {
		if swc.events[i].After(cutoff) {
			break
		}
	}
	swc.events = swc.events[i:]
}
