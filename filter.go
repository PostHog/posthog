package main

import (
	"log"
	"sync/atomic"
)

type Subscription struct {
	// Filters
	Token      string
	DistinctId string
	EventType  string

	// Response channel
	EventChan   chan PostHogEvent
	ShouldClose *atomic.Bool
}

type ResponsePostHogEvent struct {
	Timestamp  string `json:"timestamp"`
	DistinctId string `json:"distinct_id"`
	PersonId   string `json:"person_id"`
	Event      string `json:"event"`
}

type ResponseGeoEvent struct {
	Lat   float64 `json:"lat"`
	Lng   float64 `json:"lng"`
	Count int32   `json:"count"`
}

type Filter struct {
	inboundChan chan PostHogEvent
	subChan     chan Subscription
	subs        []Subscription
}

func NewFilter(subChan chan Subscription, inboundChan chan PostHogEvent) *Filter {
	return &Filter{subChan: subChan, inboundChan: inboundChan, subs: make([]Subscription, 0)}
}

func (c *Filter) Run() {
	for {
		select {
		case newSub := <-c.subChan:
			log.Printf("Adding new sub")
			c.subs = append(c.subs, newSub)
			log.Printf("Added new sub")
		case event := <-c.inboundChan:
			for _, sub := range c.subs {
				if sub.ShouldClose.Load() {
					// TODO: Figure this out later. Apparently closing from the read side is dangerous
					// because writing to a closed channel = panic.
					continue
				}

				if sub.Token != "" && event.Token != sub.Token {
					continue
				}

				if sub.DistinctId != "" && event.DistinctID != sub.DistinctId {
					continue
				}

				if sub.EventType != "" && event.Event != sub.EventType {
					continue
				}

				sub.EventChan <- event
			}
		}
	}
}
