package events

import (
	"context"
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

	RedisStore *StatsInRedis

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

func (ts *Stats) KeepStats(statsChan chan CountEvent, flushInterval time.Duration) {
	log.Printf("starting stats keeper (flush interval: %s)...", flushInterval)

	pending := make(map[string]map[string]float64)
	ticker := time.NewTicker(flushInterval)
	defer ticker.Stop()

	for {
		select {
		case event, ok := <-statsChan:
			if !ok {
				ts.flushUsersToRedis(pending)
				return
			}

			ts.Counter.Increment()
			ts.GetStoreForToken(event.Token).Add(event.DistinctID, NoSpaceType{})
			ts.GlobalStore.Add(event.DistinctID, NoSpaceType{})
			metrics.HandledEvents.Inc()

			if ts.RedisStore != nil {
				if pending[event.Token] == nil {
					pending[event.Token] = make(map[string]float64)
				}

				pending[event.Token][event.DistinctID] = float64(time.Now().Unix())
			}
		case <-ticker.C:
			ts.flushUsersToRedis(pending)
			pending = make(map[string]map[string]float64)
		}
	}
}

func (ts *Stats) flushUsersToRedis(pending map[string]map[string]float64) {
	if ts.RedisStore == nil || len(pending) == 0 {
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	ts.RedisStore.FlushUsers(ctx, pending)
}
