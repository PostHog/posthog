package main

import (
	"log"
	"time"

	"github.com/hashicorp/golang-lru/v2/expirable"
)

const (
	COUNTER_TTL = time.Minute
)

type CountEvent struct {
	Token      string
	DistinctID string
}

type noSpaceType struct{}

// Stats keeps stats for each (team) token
type Stats struct {
	Store       map[string]*expirable.LRU[string, noSpaceType]
	GlobalStore *expirable.LRU[string, noSpaceType]
	Counter     *SlidingWindowCounter
}

func newStatsKeeper() *Stats {
	return &Stats{
		Store:       make(map[string]*expirable.LRU[string, noSpaceType]),
		GlobalStore: expirable.NewLRU[string, noSpaceType](0, nil, COUNTER_TTL),
		Counter:     NewSlidingWindowCounter(COUNTER_TTL),
	}
}

func (ts *Stats) keepStats(statsChan chan CountEvent) {
	log.Println("starting stats keeper...")

	for event := range statsChan {
		ts.Counter.Increment()
		token := event.Token
		if store, ok := ts.Store[token]; !ok {
			store = expirable.NewLRU[string, noSpaceType](0, nil, COUNTER_TTL)
			store.Add(event.DistinctID, noSpaceType{})
			ts.Store[token] = store
		} else {
			ts.Store[token].Add(event.DistinctID, noSpaceType{})
		}

		ts.GlobalStore.Add(event.DistinctID, noSpaceType{})
		handledEvents.Inc()
	}
}
