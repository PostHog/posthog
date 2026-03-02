package events

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"slices"

	"github.com/posthog/posthog/livestream/configs"
	"github.com/posthog/posthog/livestream/metrics"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/redis/go-redis/v9"
)

//easyjson:json
type PubSubEvent struct {
	Token       string                 `json:"token"`
	Event       string                 `json:"event"`
	Properties  map[string]interface{} `json:"properties"`
	Timestamp   interface{}            `json:"timestamp,omitempty"`
	Uuid        string                 `json:"uuid"`
	DistinctId  string                 `json:"distinct_id"`
	Lat         float64                `json:"lat"`
	Lng         float64                `json:"lng"`
	CountryCode string                 `json:"country_code"`
}

func toPubSubEvent(e PostHogEvent) PubSubEvent {
	return PubSubEvent{
		Token:       e.Token,
		Event:       e.Event,
		Properties:  e.Properties,
		Timestamp:   e.Timestamp,
		Uuid:        e.Uuid,
		DistinctId:  e.DistinctId,
		Lat:         e.Lat,
		Lng:         e.Lng,
		CountryCode: e.CountryCode,
	}
}

func (p PubSubEvent) toPostHogEvent() PostHogEvent {
	return PostHogEvent{
		Token:       p.Token,
		Event:       p.Event,
		Properties:  p.Properties,
		Timestamp:   p.Timestamp,
		Uuid:        p.Uuid,
		DistinctId:  p.DistinctId,
		Lat:         p.Lat,
		Lng:         p.Lng,
		CountryCode: p.CountryCode,
	}
}

func channelName(token string) string {
	return fmt.Sprintf("livestream:events:%s", token)
}

type RedisEventBroker struct {
	client redis.UniversalClient
}

func NewRedisEventBroker(cfg configs.RedisConfig) (*RedisEventBroker, error) {
	client, err := newRedisClient(cfg)
	if err != nil {
		return nil, err
	}
	return &RedisEventBroker{client: client}, nil
}

func NewRedisEventBrokerFromClient(client redis.UniversalClient) *RedisEventBroker {
	return &RedisEventBroker{client: client}
}

func (b *RedisEventBroker) Publish(ctx context.Context, event PostHogEvent) {
	if event.Token == "" {
		return
	}

	data, err := json.Marshal(toPubSubEvent(event))
	if err != nil {
		log.Printf("redis publish: marshal error: %v", err)
		metrics.RedisPublishErrorsTotal.Inc()
		return
	}

	if err := b.client.Publish(ctx, channelName(event.Token), data).Err(); err != nil {
		log.Printf("redis publish: %v", err)
		metrics.RedisPublishErrorsTotal.Inc()
		return
	}

	metrics.RedisPublishTotal.Inc()
}

func (b *RedisEventBroker) Close() error {
	return b.client.Close()
}

func NewRedisUniversalClient(cfg configs.RedisConfig) (redis.UniversalClient, error) {
	return newRedisClient(cfg)
}

type TokenRouter struct {
	client    redis.UniversalClient
	SubChan   chan Subscription
	UnSubChan chan Subscription
	tokenSubs map[string][]Subscription
	allSubs   map[uint64]Subscription
	redisSub  *redis.PubSub
}

func NewTokenRouter(client redis.UniversalClient, subChan, unSubChan chan Subscription) *TokenRouter {
	return &TokenRouter{
		client:    client,
		SubChan:   subChan,
		UnSubChan: unSubChan,
		tokenSubs: make(map[string][]Subscription),
		allSubs:   make(map[uint64]Subscription),
		redisSub:  client.Subscribe(context.Background()),
	}
}

func (tr *TokenRouter) Run(ctx context.Context) {
	msgCh := tr.redisSub.Channel()

	defer func() {
		_ = tr.redisSub.Close()
	}()

	for {
		select {
		case <-ctx.Done():
			return

		case newSub := <-tr.SubChan:
			token := newSub.Token
			tr.allSubs[newSub.SubID] = newSub
			tr.tokenSubs[token] = append(tr.tokenSubs[token], newSub)
			metrics.SubTotal.Inc()

			if len(tr.tokenSubs[token]) == 1 {
				if err := tr.redisSub.Subscribe(ctx, channelName(token)); err != nil {
					log.Printf("redis subscribe %s: %v", token, err)
				} else {
					metrics.RedisSubscribeTotal.Inc()
				}
			}

		case unSub := <-tr.UnSubChan:
			sub, exists := tr.allSubs[unSub.SubID]
			if !exists {
				continue
			}
			token := sub.Token
			delete(tr.allSubs, unSub.SubID)

			if dropped := sub.DroppedEvents.Load(); dropped > 0 {
				log.Printf("Team %d dropped %d events", sub.TeamId, dropped)
			}
			metrics.SubTotal.Dec()

			subs := tr.tokenSubs[token]
			for i, s := range subs {
				if s.SubID == unSub.SubID {
					tr.tokenSubs[token] = slices.Delete(subs, i, i+1)
					break
				}
			}

			if len(tr.tokenSubs[token]) == 0 {
				delete(tr.tokenSubs, token)
				if err := tr.redisSub.Unsubscribe(ctx, channelName(token)); err != nil {
					log.Printf("redis unsubscribe %s: %v", token, err)
				} else {
					metrics.RedisSubscribeTotal.Dec()
				}
			}

		case msg, ok := <-msgCh:
			if !ok {
				log.Printf("redis pubsub channel closed, exiting")
				return
			}
			metrics.RedisMessagesReceivedTotal.Inc()

			var pse PubSubEvent
			if err := json.Unmarshal([]byte(msg.Payload), &pse); err != nil {
				log.Printf("redis message unmarshal: %v", err)
				continue
			}

			event := pse.toPostHogEvent()
			token := pse.Token
			subs := tr.tokenSubs[token]

			var responseGeoEvent *ResponseGeoEvent

			for _, sub := range subs {
				if sub.ShouldClose.Load() {
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
							sub.DroppedEvents.Add(1)
							metrics.DroppedEvents.With(prometheus.Labels{"channel": "geo"}).Inc()
						}
					}
				} else {
					responseEvent := convertToResponsePostHogEvent(event, sub.TeamId, sub.Columns)
					select {
					case sub.EventChan <- *responseEvent:
					default:
						sub.DroppedEvents.Add(1)
						metrics.DroppedEvents.With(prometheus.Labels{"channel": "events"}).Inc()
					}
				}
			}
		}
	}
}
