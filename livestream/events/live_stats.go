package events

import (
	"log"
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
	// Store keeps distinct users ID's for a given token
	Store map[string]*expirable.LRU[string, NoSpaceType]
	// GlobalStore keeps all user ids globally, used only for count.
	GlobalStore *expirable.LRU[string, NoSpaceType]
	// Counter keeps all events count in the last COUNTER_TTL
	Counter *SlidingWindowCounter
}

func NewStatsKeeper() *Stats {
	return &Stats{
		Store:       make(map[string]*expirable.LRU[string, NoSpaceType]),
		GlobalStore: expirable.NewLRU[string, NoSpaceType](0, nil, COUNTER_TTL),
		Counter:     NewSlidingWindowCounter(COUNTER_TTL),
	}
}

func (ts *Stats) KeepStats(statsChan chan CountEvent) {
	log.Println("starting stats keeper...")

	for event := range statsChan {
		ts.Counter.Increment()
		token := event.Token
		store, ok := ts.Store[token]
		if !ok {
			store = expirable.NewLRU[string, NoSpaceType](0, nil, COUNTER_TTL)
			ts.Store[token] = store
		}
		store.Add(event.DistinctID, NoSpaceType{})

		ts.GlobalStore.Add(event.DistinctID, NoSpaceType{})
		metrics.HandledEvents.Inc()
	}
}
