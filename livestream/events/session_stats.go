package events

import (
	"context"
	"log"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/hashicorp/golang-lru/v2/expirable"
	"github.com/posthog/posthog/livestream/metrics"
)

const sessionRecordingTTL = 5 * time.Minute
const DefaultMaxSessionRecordingEntries = 2000000

type SessionStats struct {
	// Single LRU with composite keys "token:sessionId"
	// This avoids creating one LRU (and one goroutine) per token
	store *expirable.LRU[string, string]

	// Track counts per token for O(1) lookups
	// The eviction callback (onEvict) decrements these when entries expire or get evicted
	counts   map[string]*atomic.Int64
	countsMu sync.RWMutex

	// Mutex for Add operations to prevent race between existence check and counter increment
	addMu sync.Mutex
}

// NewSessionStatsKeeper creates a new SessionStats with the specified max LRU entries.
// If maxEntries is 0, uses DefaultMaxSessionRecordingEntries.
func NewSessionStatsKeeper(maxEntries int) *SessionStats {
	if maxEntries <= 0 {
		maxEntries = DefaultMaxSessionRecordingEntries
	}

	ss := &SessionStats{
		counts: make(map[string]*atomic.Int64),
	}

	// Single LRU instance = single background goroutine
	// Using composite key "token:sessionId" and storing token as value
	// so we can decrement the right counter on eviction
	ss.store = expirable.NewLRU[string, string](
		maxEntries,
		ss.onEvict,
		sessionRecordingTTL,
	)

	log.Printf("Session recording stats keeper initialized with max LRU entries: %d", maxEntries)
	return ss
}

// onEvict is called when an entry is evicted (by LRU or TTL)
func (ss *SessionStats) onEvict(key string, token string) {
	ss.countsMu.RLock()
	counter := ss.counts[token]
	ss.countsMu.RUnlock()

	if counter != nil {
		counter.Add(-1)
	}
	metrics.SessionRecordingLRUEvictions.Inc()
}

// getOrCreateCounter returns the counter for a token, creating if needed
func (ss *SessionStats) getOrCreateCounter(token string) *atomic.Int64 {
	ss.countsMu.RLock()
	counter := ss.counts[token]
	ss.countsMu.RUnlock()

	if counter != nil {
		return counter
	}

	ss.countsMu.Lock()
	counter = ss.counts[token]
	if counter == nil {
		counter = &atomic.Int64{}
		ss.counts[token] = counter
	}
	ss.countsMu.Unlock()
	return counter
}

// CountForToken returns the number of active sessions for a token
func (ss *SessionStats) CountForToken(token string) int {
	ss.countsMu.RLock()
	counter := ss.counts[token]
	ss.countsMu.RUnlock()

	if counter == nil {
		return 0
	}
	count := counter.Load()
	if count < 0 {
		return 0
	}
	return int(count)
}

// Add adds a session for a token
func (ss *SessionStats) Add(token, sessionId string) {
	key := token + ":" + sessionId

	// Lock to prevent race between existence check and counter increment
	// This ensures two concurrent Add() calls for the same key don't both increment
	ss.addMu.Lock()
	defer ss.addMu.Unlock()

	// Check if already exists (don't double-count)
	if ss.store.Contains(key) {
		// Refresh TTL by re-adding
		ss.store.Add(key, token)
		return
	}

	// New entry - add to LRU and increment counter
	ss.store.Add(key, token)
	ss.getOrCreateCounter(token).Add(1)
}

func (ss *SessionStats) KeepStats(ctx context.Context, statsChan chan SessionRecordingEvent) {
	log.Println("starting session recording stats keeper...")

	cleanupTicker := time.NewTicker(10 * time.Minute)
	defer cleanupTicker.Stop()

	metricsTicker := time.NewTicker(10 * time.Second)
	defer metricsTicker.Stop()

	for {
		select {
		case <-ctx.Done():
			log.Println("session recording stats keeper shutting down...")
			return
		case <-cleanupTicker.C:
			ss.cleanupEmptyCounters()
		case <-metricsTicker.C:
			metrics.SessionRecordingLRUSize.Set(float64(ss.Len()))
			metrics.SessionRecordingTokenCount.Set(float64(ss.TokenCount()))
		case event := <-statsChan:
			ss.Add(event.Token, event.SessionId)
			metrics.SessionRecordingHandledEvents.Inc()
		}
	}
}

// cleanupEmptyCounters removes counters that have dropped to zero
func (ss *SessionStats) cleanupEmptyCounters() {
	ss.countsMu.Lock()
	defer ss.countsMu.Unlock()

	for token, counter := range ss.counts {
		if counter.Load() <= 0 {
			delete(ss.counts, token)
		}
	}
}

// Len returns total number of tracked sessions across all tokens
func (ss *SessionStats) Len() int {
	return ss.store.Len()
}

// --- Deprecated methods for backwards compatibility ---
// These exist to minimize changes to handlers during migration

// GetExistingStoreForToken is deprecated - use CountForToken instead
// Returns nil if token has no sessions (for backwards compat with nil checks)
func (ss *SessionStats) GetExistingStoreForToken(token string) *tokenSessionStore {
	if ss.CountForToken(token) == 0 {
		return nil
	}
	return &tokenSessionStore{ss: ss, token: token}
}

// tokenSessionStore is a shim that provides Len() for backwards compatibility
type tokenSessionStore struct {
	ss    *SessionStats
	token string
}

func (t *tokenSessionStore) Len() int {
	return t.ss.CountForToken(t.token)
}

// --- Helper for debugging ---

// TokenCount returns number of unique tokens being tracked
func (ss *SessionStats) TokenCount() int {
	ss.countsMu.RLock()
	defer ss.countsMu.RUnlock()
	return len(ss.counts)
}

// KeysForToken returns all session IDs for a token (for debugging)
func (ss *SessionStats) KeysForToken(token string) []string {
	prefix := token + ":"
	var sessions []string
	for _, key := range ss.store.Keys() {
		if strings.HasPrefix(key, prefix) {
			sessions = append(sessions, strings.TrimPrefix(key, prefix))
		}
	}
	return sessions
}
