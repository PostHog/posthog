package events

import (
	"context"
	"sync"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

func TestNewSessionStatsKeeper(t *testing.T) {
	ss := NewSessionStatsKeeper(0, 0) // 0 uses default

	assert.NotNil(t, ss.store)
	assert.NotNil(t, ss.counts)
}

func TestNewSessionStatsKeeper_CustomSize(t *testing.T) {
	ss := NewSessionStatsKeeper(100, 0)

	assert.NotNil(t, ss.store)
	assert.NotNil(t, ss.counts)
}

func TestSessionStats_Add(t *testing.T) {
	ss := NewSessionStatsKeeper(0, 0)

	// Add first session
	ss.Add("token1", "session1")
	assert.Equal(t, 1, ss.CountForToken("token1"))

	// Add same session again (should not increment)
	ss.Add("token1", "session1")
	assert.Equal(t, 1, ss.CountForToken("token1"))

	// Add different session same token
	ss.Add("token1", "session2")
	assert.Equal(t, 2, ss.CountForToken("token1"))

	// Add session for different token
	ss.Add("token2", "session3")
	assert.Equal(t, 1, ss.CountForToken("token2"))
	assert.Equal(t, 2, ss.CountForToken("token1")) // unchanged
}

func TestSessionStats_GetExistingStoreForToken(t *testing.T) {
	ss := NewSessionStatsKeeper(0, 0)

	// Non-existent token returns zero
	count := ss.CountForToken("nonexistent")
	assert.Zero(t, count)

	// After adding a session, returns non-nil with correct count
	ss.Add("token1", "session1")
	count = ss.CountForToken("token1")
	assert.NotNil(t, count)
	assert.Equal(t, 1, count)
}

func TestSessionStats_Count(t *testing.T) {
	tests := []struct {
		name            string
		events          []SessionRecordingEvent
		wantToken1Count int
		wantToken2Count int
	}{
		{
			name:            "empty",
			events:          nil,
			wantToken1Count: 0,
			wantToken2Count: 0,
		},
		{
			name: "single session",
			events: []SessionRecordingEvent{
				{Token: "t1", SessionId: "s1"},
			},
			wantToken1Count: 1,
			wantToken2Count: 0,
		},
		{
			name: "same session twice",
			events: []SessionRecordingEvent{
				{Token: "t1", SessionId: "s1"},
				{Token: "t1", SessionId: "s1"},
			},
			wantToken1Count: 1,
			wantToken2Count: 0,
		},
		{
			name: "different sessions same token",
			events: []SessionRecordingEvent{
				{Token: "t1", SessionId: "s1"},
				{Token: "t1", SessionId: "s2"},
			},
			wantToken1Count: 2,
			wantToken2Count: 0,
		},
		{
			name: "different tokens",
			events: []SessionRecordingEvent{
				{Token: "t1", SessionId: "s1"},
				{Token: "t2", SessionId: "s2"},
			},
			wantToken1Count: 1,
			wantToken2Count: 1,
		},
		{
			name: "same session different tokens",
			events: []SessionRecordingEvent{
				{Token: "t1", SessionId: "s1"},
				{Token: "t2", SessionId: "s1"},
			},
			wantToken1Count: 1,
			wantToken2Count: 1,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ss := NewSessionStatsKeeper(0, 0)
			statsChan := make(chan SessionRecordingEvent, 100)
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()

			go ss.KeepStats(ctx, statsChan)

			for _, event := range tt.events {
				statsChan <- event
			}

			time.Sleep(50 * time.Millisecond)
			cancel()
			time.Sleep(10 * time.Millisecond)

			assert.Equal(t, tt.wantToken1Count, ss.CountForToken("t1"))
			assert.Equal(t, tt.wantToken2Count, ss.CountForToken("t2"))

		})
	}
}

func TestSessionStats_Concurrency(t *testing.T) {
	ss := NewSessionStatsKeeper(0, 0)
	statsChan := make(chan SessionRecordingEvent, 1000)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	go ss.KeepStats(ctx, statsChan)

	iterations := 100
	var wg sync.WaitGroup
	wg.Add(iterations)

	for i := 0; i < iterations; i++ {
		go func(idx int) {
			defer wg.Done()
			statsChan <- SessionRecordingEvent{
				Token:     "token1",
				SessionId: "session1",
			}
		}(i)
	}

	wg.Wait()
	time.Sleep(50 * time.Millisecond)
	cancel()
	time.Sleep(10 * time.Millisecond)

	// Same session sent 100 times should still be count of 1
	assert.Equal(t, 1, ss.CountForToken("token1"))
}

func TestSessionStats_CleanupEmptyCounters(t *testing.T) {
	ss := NewSessionStatsKeeper(0, 100*time.Millisecond)
	ss.Add("token", "session1")
	ss.Add("token2", "session2")
	assert.Equal(t, 2, ss.TokenCount())
	time.Sleep(200 * time.Millisecond)
	assert.Equal(t, 0, ss.TokenCount())
}

func TestSessionStats_TokenCount(t *testing.T) {
	ss := NewSessionStatsKeeper(0, 0)

	assert.Equal(t, 0, ss.TokenCount())

	ss.Add("token1", "session1")
	assert.Equal(t, 1, ss.TokenCount())

	ss.Add("token2", "session2")
	assert.Equal(t, 2, ss.TokenCount())

	// Same token different session doesn't change token count
	ss.Add("token1", "session3")
	assert.Equal(t, 2, ss.TokenCount())
}

func TestSessionStats_Len(t *testing.T) {
	ss := NewSessionStatsKeeper(0, 0)

	assert.Equal(t, 0, ss.Len())

	ss.Add("token1", "session1")
	assert.Equal(t, 1, ss.Len())

	ss.Add("token1", "session2")
	assert.Equal(t, 2, ss.Len())

	ss.Add("token2", "session3")
	assert.Equal(t, 3, ss.Len())

	// Duplicate doesn't increase total
	ss.Add("token1", "session1")
	assert.Equal(t, 3, ss.Len())
}

func TestSessionStats_KeysForToken(t *testing.T) {
	ss := NewSessionStatsKeeper(0, 0)

	// Empty
	keys := ss.KeysForToken("token1")
	assert.Empty(t, keys)

	// Add sessions
	ss.Add("token1", "session1")
	ss.Add("token1", "session2")
	ss.Add("token2", "session3")

	keys = ss.KeysForToken("token1")
	assert.Len(t, keys, 2)
	assert.Contains(t, keys, "session1")
	assert.Contains(t, keys, "session2")

	keys = ss.KeysForToken("token2")
	assert.Len(t, keys, 1)
	assert.Contains(t, keys, "session3")
}
