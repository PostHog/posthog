package main

import (
	"sync/atomic"
)

type Subscription struct {
	// Filters
	Token      string
	DistinctId string
	EventType  string

	// Response channel
	EventChan   chan ResponsePostHogEvent
	ShouldClose *atomic.Bool
}

type ResponsePostHogEvent struct {
	Uuid       string                 `json:"uuid"`
	Timestamp  string                 `json:"timestamp"`
	DistinctId string                 `json:"distinct_id"`
	PersonId   string                 `json:"person_id"`
	Event      string                 `json:"event"`
	Properties map[string]interface{} `json:"properties"`
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

func convertToResponsePostHogEvent(event PostHogEvent) *ResponsePostHogEvent {
	return &ResponsePostHogEvent{
		Uuid:       event.Uuid,
		Timestamp:  event.Timestamp,
		DistinctId: event.DistinctID,
		PersonId:   "TODO",
		Event:      event.Event,
		Properties: event.Properties,
	}
}

func (c *Filter) Run() {
	i := 0
	for {
		select {
		case newSub := <-c.subChan:
			c.subs = append(c.subs, newSub)
		case event := <-c.inboundChan:
			var responseEvent *ResponsePostHogEvent

			i += 1
			if i%1000 == 0 {
				for _, sub := range c.subs {
					if sub.ShouldClose.Load() {
						// TODO: Figure this out later. Apparently closing from the read side is dangerous
						// because writing to a closed channel = panic.
						continue
					}

					// log.Printf("event.Token: %s, sub.Token: %s", event.Token, sub.Token)
					// if sub.Token != "" && event.Token != sub.Token {
					// 	continue
					// }

					// if sub.DistinctId != "" && event.DistinctID != sub.DistinctId {
					// 	continue
					// }

					// if sub.EventType != "" && event.Event != sub.EventType {
					// 	continue
					// }

					if responseEvent == nil {
						responseEvent = convertToResponsePostHogEvent(event)
					}

					sub.EventChan <- *responseEvent
				}
			}
		}
	}
}
