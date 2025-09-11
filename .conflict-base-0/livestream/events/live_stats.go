package events

import (
	"log"
	"sync"
	"time"

	"github.com/hashicorp/golang-lru/v2/expirable"
	"github.com/posthog/posthog/livestream/metrics"
)

const (
	COUNTER_TTL = time.Minute
)

type CountEvent struct {
	Token      string
	DistinctID string
}

type NoSpaceType struct{}

// Stats keeps stats for each (team) token
type Stats struct {
	// store keeps distinct users ID's for a given token
	store map[string]*expirable.LRU[string, NoSpaceType]
	// GlobalStore keeps all user ids globally, used only for count.
	GlobalStore *expirable.LRU[string, NoSpaceType]
	// Counter keeps all events count in the last COUNTER_TTL
	Counter *SlidingWindowCounter

	mu sync.RWMutex // guards store
}

func NewStatsKeeper() *Stats {
	return &Stats{
		store:       make(map[string]*expirable.LRU[string, NoSpaceType]),
		GlobalStore: expirable.NewLRU[string, NoSpaceType](0, nil, COUNTER_TTL),
		Counter:     NewSlidingWindowCounter(COUNTER_TTL),
	}
}

func (ts *Stats) GetExistingStoreForToken(token string) *expirable.LRU[string, NoSpaceType] {
	ts.mu.RLock()
	defer ts.mu.RUnlock()
	return ts.store[token]
}

func (ts *Stats) GetStoreForToken(token string) *expirable.LRU[string, NoSpaceType] {
	store := ts.GetExistingStoreForToken(token)
	if store != nil {
		return store
	}
	ts.mu.Lock()
	store = ts.store[token]
	if store == nil {
		store = expirable.NewLRU[string, NoSpaceType](0, nil, COUNTER_TTL)
		ts.store[token] = store
	}
	ts.mu.Unlock()
	return store
}

func (ts *Stats) KeepStats(statsChan chan CountEvent) {
	log.Println("starting stats keeper...")

	for event := range statsChan {
		ts.Counter.Increment()
		ts.GetStoreForToken(event.Token).Add(event.DistinctID, NoSpaceType{})
		ts.GlobalStore.Add(event.DistinctID, NoSpaceType{})
		metrics.HandledEvents.Inc()
	}
}
