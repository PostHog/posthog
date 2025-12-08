package events

import (
	"log"
	"sync"
	"time"

	"github.com/hashicorp/golang-lru/v2/expirable"
	"github.com/posthog/posthog/livestream/metrics"
)

const SESSION_RECORDING_TTL = 5 * time.Minute

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
		store = expirable.NewLRU[string, NoSpaceType](0, nil, SESSION_RECORDING_TTL)
		ss.store[token] = store
	}
	ss.mu.Unlock()
	return store
}

func (ss *SessionStats) KeepStats(statsChan chan SessionRecordingEvent) {
	log.Println("starting session recording stats keeper...")

	for event := range statsChan {
		ss.GetStoreForToken(event.Token).Add(event.SessionId, NoSpaceType{})
		metrics.SessionRecordingHandledEvents.Inc()
	}
}
