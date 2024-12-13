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
	TeamId     int
	Token      string
	DistinctId string
	EventTypes []string

	Geo bool

	// Channels
	EventChan   chan interface{}
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

func convertToResponseGeoEvent(event PostHogEvent) *ResponseGeoEvent {
	return &ResponseGeoEvent{
		Lat:   event.Lat,
		Lng:   event.Lng,
		Count: 1,
	}
}

func convertToResponsePostHogEvent(event PostHogEvent, teamId int) *ResponsePostHogEvent {
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

func uuidFromDistinctId(teamId int, distinctId string) string {
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
	for {
		select {
		case newSub := <-c.subChan:
			c.subs = append(c.subs, newSub)
		case unSub := <-c.unSubChan:
			c.subs = removeSubscription(unSub.ClientId, c.subs)
		case event := <-c.inboundChan:
			var responseEvent *ResponsePostHogEvent
			var responseGeoEvent *ResponseGeoEvent

			for _, sub := range c.subs {
				if sub.ShouldClose.Load() {
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

				if len(sub.EventTypes) > 0 && !slices.Contains(sub.EventTypes, event.Event) {
					continue
				}

				if sub.Geo {
					if event.Lat != 0.0 {
						if responseGeoEvent == nil {
							responseGeoEvent = convertToResponseGeoEvent(event)
						}

						select {
						case sub.EventChan <- *responseGeoEvent:
						default:
							// Don't block
						}
					}
				} else {
					if responseEvent == nil {
						responseEvent = convertToResponsePostHogEvent(event, sub.TeamId)
					}

					select {
					case sub.EventChan <- *responseEvent:
					default:
						// Don't block
					}
				}
			}

		}
	}
}
