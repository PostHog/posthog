package events

import (
	"context"
	"log"
	"sync"
	"time"

	"github.com/hashicorp/golang-lru/v2/expirable"
	"github.com/posthog/posthog/livestream/metrics"
)

const sessionRecordingTTL = 5 * time.Minute

type SessionStats struct {
	store map[string]*expirable.LRU[string, NoSpaceType]
	mu    sync.RWMutex
}

func NewSessionStatsKeeper() *SessionStats {
	return &SessionStats{
		store: make(map[string]*expirable.LRU[string, NoSpaceType]),
	}
}

func (ss *SessionStats) GetExistingStoreForToken(token string) *expirable.LRU[string, NoSpaceType] {
	ss.mu.RLock()
	defer ss.mu.RUnlock()
	return ss.store[token]
}

func (ss *SessionStats) GetStoreForToken(token string) *expirable.LRU[string, NoSpaceType] {
	store := ss.GetExistingStoreForToken(token)
	if store != nil {
		return store
	}
	ss.mu.Lock()
	store = ss.store[token]
	if store == nil {
		store = expirable.NewLRU[string, NoSpaceType](0, nil, sessionRecordingTTL)
		ss.store[token] = store
	}
	ss.mu.Unlock()
	return store
}

func (ss *SessionStats) KeepStats(ctx context.Context, statsChan chan SessionRecordingEvent) {
	log.Println("starting session recording stats keeper...")

	cleanupTicker := time.NewTicker(10 * time.Minute)
	defer cleanupTicker.Stop()

	for {
		select {
		case <-ctx.Done():
			log.Println("session recording stats keeper shutting down...")
			return
		case <-cleanupTicker.C:
			ss.cleanupEmptyStores()
		case event := <-statsChan:
			ss.GetStoreForToken(event.Token).Add(event.SessionId, NoSpaceType{})
			metrics.SessionRecordingHandledEvents.Inc()
		}
	}
}

func (ss *SessionStats) cleanupEmptyStores() {
	ss.mu.Lock()
	defer ss.mu.Unlock()

	for token, store := range ss.store {
		if store.Len() == 0 {
			delete(ss.store, token)
		}
	}
}
