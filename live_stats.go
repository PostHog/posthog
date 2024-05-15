package main

import (
	"log"
	"time"

	"github.com/hashicorp/golang-lru/v2/expirable"
)

type TeamStats struct {
	Store map[string]*expirable.LRU[string, string]
}

func (ts *TeamStats) keepStats(statsChan chan PostHogEvent) {
	log.Println("starting stats keeper...")
	for {
		select {
		case event := <-statsChan:
			token := event.Token
			if _, ok := ts.Store[token]; !ok {
				ts.Store[token] = expirable.NewLRU[string, string](1000000, nil, time.Second*30)
			}
			ts.Store[token].Add(event.DistinctId, "much wow")
		}
	}
}
