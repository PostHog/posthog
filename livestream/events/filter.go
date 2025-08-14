package events

import (
	"fmt"
	"log"
	"slices"
	"sync/atomic"

	"github.com/gofrs/uuid/v5"
	"github.com/posthog/posthog/livestream/metrics"
)

type Subscription struct {
	SubID uint64

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

//easyjson:json
type ResponsePostHogEvent struct {
	Uuid       string                 `json:"uuid"`
	Timestamp  interface{}            `json:"timestamp"`
	DistinctId string                 `json:"distinct_id"`
	PersonId   string                 `json:"person_id"`
	Event      string                 `json:"event"`
	Properties map[string]interface{} `json:"properties"`
}

//easyjson:json
type ResponseGeoEvent struct {
	Lat   float64 `json:"lat"`
	Lng   float64 `json:"lng"`
	Count uint    `json:"count"`
}

type Filter struct {
	inboundChan chan PostHogEvent
	SubChan     chan Subscription
	UnSubChan   chan Subscription
	subs        []Subscription
}

func NewFilter(subChan chan Subscription, unSubChan chan Subscription, inboundChan chan PostHogEvent) *Filter {
	return &Filter{SubChan: subChan, UnSubChan: unSubChan, inboundChan: inboundChan, subs: make([]Subscription, 0)}
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

var personUUIDV5Namespace = uuid.Must(uuid.FromString("932979b4-65c3-4424-8467-0b66ec27bc22"))

func uuidFromDistinctId(teamId int, distinctId string) string {
	if teamId == 0 || distinctId == "" {
		return ""
	}

	input := fmt.Sprintf("%d:%s", teamId, distinctId)
	return uuid.NewV5(personUUIDV5Namespace, input).String()
}

func removeSubscription(subID uint64, subs []Subscription) []Subscription {
	for i, sub := range subs {
		if subID == sub.SubID {
			metrics.SubTotal.Dec()
			return slices.Delete(subs, i, i+1)
		}
	}
	return subs
}

func (c *Filter) Run() {
	for {
		select {
		case newSub := <-c.SubChan:
			c.subs = append(c.subs, newSub)
			metrics.SubTotal.Inc()
		case unSub := <-c.UnSubChan:
			c.subs = removeSubscription(unSub.SubID, c.subs)
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
