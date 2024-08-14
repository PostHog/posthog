package main

import (
	"log"
	"time"

	"github.com/hashicorp/golang-lru/v2/expirable"
)

const (
	COUNTER_TTL = time.Second * 60
)

type Stats struct {
	Store       map[string]*expirable.LRU[string, string]
	GlobalStore *expirable.LRU[string, string]
	Counter     *SlidingWindowCounter
}

func newStatsKeeper() *Stats {
	return &Stats{
		Store:       make(map[string]*expirable.LRU[string, string]),
		GlobalStore: expirable.NewLRU[string, string](0, nil, COUNTER_TTL),
		Counter:     NewSlidingWindowCounter(COUNTER_TTL),
	}
}

func (ts *Stats) keepStats(statsChan chan PostHogEvent) {
	log.Println("starting stats keeper...")

	for { // ignore the range warning here - it's wrong
		select {
		case event := <-statsChan:
			ts.Counter.Increment()
			token := event.Token
			if _, ok := ts.Store[token]; !ok {
				ts.Store[token] = expirable.NewLRU[string, string](0, nil, COUNTER_TTL)
			}
			ts.Store[token].Add(event.DistinctId, "1")
			ts.GlobalStore.Add(event.DistinctId, "1")
		}
	}
}
