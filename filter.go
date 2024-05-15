package main

import (
	"fmt"
	"log"
	"sync/atomic"

	"github.com/gofrs/uuid/v5"
	"golang.org/x/exp/slices"
)

type Subscription struct {
	// Client
	ClientId string

	// Filters
	TeamId     uint
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
	Count uint    `json:"count"`
}

type Filter struct {
	inboundChan chan PostHogEvent
	subChan     chan Subscription
	unSubChan   chan Subscription
	subs        []Subscription
}

func NewFilter(subChan chan Subscription, unSubChan chan Subscription, inboundChan chan PostHogEvent) *Filter {
	return &Filter{subChan: subChan, unSubChan: unSubChan, inboundChan: inboundChan, subs: make([]Subscription, 0)}
}

func convertToResponsePostHogEvent(event PostHogEvent, teamId uint) *ResponsePostHogEvent {
	return &ResponsePostHogEvent{
		Uuid:       event.Uuid,
		Timestamp:  event.Timestamp,
		DistinctId: event.DistinctId,
		PersonId:   uuidFromDistinctId(teamId, event.DistinctId),
		Event:      event.Event,
		Properties: event.Properties,
	}
}

var personUUIDV5Namespace *uuid.UUID

func uuidFromDistinctId(teamId uint, distinctId string) string {
	if teamId == 0 || distinctId == "" {
		return ""
	}

	if personUUIDV5Namespace == nil {
		uuid, _ := uuid.FromString("932979b4-65c3-4424-8467-0b66ec27bc22")
		personUUIDV5Namespace = &uuid
	}

	input := fmt.Sprintf("%d:%s", teamId, distinctId)
	return uuid.NewV5(*personUUIDV5Namespace, input).String()
}

func removeSubscription(clientId string, subs []Subscription) []Subscription {
	var lighterSubs []Subscription
	for i, sub := range subs {
		if clientId == sub.ClientId {
			lighterSubs = slices.Delete(subs, i, i+1)
		}
	}
	return lighterSubs
}

func (c *Filter) Run() {
	i := 0
	for {
		select {
		case newSub := <-c.subChan:
			c.subs = append(c.subs, newSub)
		case unSub := <-c.unSubChan:
			removeSubscription(unSub.ClientId, c.subs)
		case event := <-c.inboundChan:
			var responseEvent *ResponsePostHogEvent

			i += 1
			if i%1000 == 0 {
				for _, sub := range c.subs {
					if sub.ShouldClose.Load() {
						// TODO: Figure this out later. Apparently closing from the read side is dangerous
						// because writing to a closed channel = panic.
						log.Println("User has unsubscribed, but not been removed from the slice of subs")
						continue
					}

					// log.Printf("event.Token: %s, sub.Token: %s", event.Token, sub.Token)
					if sub.Token != "" && event.Token != sub.Token {
						continue
					}

					if sub.DistinctId != "" && event.DistinctId != sub.DistinctId {
						continue
					}

					if sub.EventType != "" && event.Event != sub.EventType {
						continue
					}

					if responseEvent == nil {
						responseEvent = convertToResponsePostHogEvent(event, sub.TeamId)
					}

					sub.EventChan <- *responseEvent
				}
			}
		}
	}
}
