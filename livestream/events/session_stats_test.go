package events

import (
	"context"
	"sync"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

func TestNewSessionStatsKeeper(t *testing.T) {
	ss := NewSessionStatsKeeper()

	assert.NotNil(t, ss.store)
}

func TestSessionStats_GetStoreForToken(t *testing.T) {
	ss := NewSessionStatsKeeper()

	store1 := ss.GetStoreForToken("token1")
	assert.NotNil(t, store1)

	store2 := ss.GetStoreForToken("token1")
	assert.Equal(t, store1, store2)

	store3 := ss.GetStoreForToken("token2")
	assert.NotNil(t, store3)
	assert.NotEqual(t, store1, store3)
}

func TestSessionStats_GetExistingStoreForToken(t *testing.T) {
	ss := NewSessionStatsKeeper()

	store := ss.GetExistingStoreForToken("nonexistent")
	assert.Nil(t, store)

	ss.GetStoreForToken("token1")
	store = ss.GetExistingStoreForToken("token1")
	assert.NotNil(t, store)
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
			ss := NewSessionStatsKeeper()
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

			if tt.wantToken1Count > 0 {
				store := ss.GetExistingStoreForToken("t1")
				assert.NotNil(t, store)
				assert.Equal(t, tt.wantToken1Count, store.Len())
			}

			if tt.wantToken2Count > 0 {
				store := ss.GetExistingStoreForToken("t2")
				assert.NotNil(t, store)
				assert.Equal(t, tt.wantToken2Count, store.Len())
			}
		})
	}
}

func TestSessionStats_Concurrency(t *testing.T) {
	ss := NewSessionStatsKeeper()
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

	store := ss.GetExistingStoreForToken("token1")
	assert.NotNil(t, store)
	assert.Equal(t, 1, store.Len())
}

func TestSessionStats_CleanupEmptyStores(t *testing.T) {
	tests := []struct {
		name           string
		setup          func(ss *SessionStats)
		wantToken1     bool
		wantToken2     bool
		wantStoreCount int
	}{
		{
			name: "removes empty stores",
			setup: func(ss *SessionStats) {
				ss.GetStoreForToken("token1")
				ss.GetStoreForToken("token2")
			},
			wantToken1:     false,
			wantToken2:     false,
			wantStoreCount: 0,
		},
		{
			name: "preserves non-empty stores",
			setup: func(ss *SessionStats) {
				ss.GetStoreForToken("token1").Add("session1", NoSpaceType{})
				ss.GetStoreForToken("token2").Add("session2", NoSpaceType{})
			},
			wantToken1:     true,
			wantToken2:     true,
			wantStoreCount: 2,
		},
		{
			name: "removes only empty stores",
			setup: func(ss *SessionStats) {
				ss.GetStoreForToken("token1").Add("session1", NoSpaceType{})
				ss.GetStoreForToken("token2")
			},
			wantToken1:     true,
			wantToken2:     false,
			wantStoreCount: 1,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ss := NewSessionStatsKeeper()
			tt.setup(ss)

			ss.cleanupEmptyStores()

			if tt.wantToken1 {
				assert.NotNil(t, ss.GetExistingStoreForToken("token1"))
			} else {
				assert.Nil(t, ss.GetExistingStoreForToken("token1"))
			}

			if tt.wantToken2 {
				assert.NotNil(t, ss.GetExistingStoreForToken("token2"))
			} else {
				assert.Nil(t, ss.GetExistingStoreForToken("token2"))
			}

			ss.mu.RLock()
			assert.Equal(t, tt.wantStoreCount, len(ss.store))
			ss.mu.RUnlock()
		})
	}
}
