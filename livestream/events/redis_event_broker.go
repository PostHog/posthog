package events

import (
	"context"
	"fmt"
	"log"
	"slices"
	"time"

	"github.com/posthog/posthog/livestream/configs"
	"github.com/posthog/posthog/livestream/metrics"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/redis/rueidis"
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
	client rueidis.Client
}

func NewRedisEventBroker(cfg configs.RedisConfig) (*RedisEventBroker, error) {
	client, err := newRedisClient(cfg)
	if err != nil {
		return nil, err
	}
	return &RedisEventBroker{client: client}, nil
}

func NewRedisEventBrokerFromClient(client rueidis.Client) *RedisEventBroker {
	return &RedisEventBroker{client: client}
}

func (b *RedisEventBroker) Publish(ctx context.Context, event PostHogEvent) {
	if event.Token == "" {
		return
	}

	pse := toPubSubEvent(event)
	data, err := pse.MarshalJSON()
	if err != nil {
		log.Printf("redis publish: marshal error: %v", err)
		metrics.RedisPublishErrorsTotal.Inc()
		return
	}

	if err := b.client.Do(ctx, b.client.B().Spublish().Channel(channelName(event.Token)).Message(string(data)).Build()).Error(); err != nil {
		log.Printf("redis publish: %v", err)
		metrics.RedisPublishErrorsTotal.Inc()
		return
	}

	metrics.RedisPublishTotal.Inc()
}

func (b *RedisEventBroker) Close() {
	b.client.Close()
}

func NewRedisClient(cfg configs.RedisConfig) (rueidis.Client, error) {
	return newRedisClient(cfg)
}

type TokenRouter struct {
	client         rueidis.Client
	SubChan        chan Subscription
	UnSubChan      chan Subscription
	tokenSubs      map[string][]Subscription
	allSubs        map[uint64]Subscription
	msgCh          chan rueidis.PubSubMessage
	channelCancels map[string]context.CancelFunc
}

func NewTokenRouter(client rueidis.Client, subChan, unSubChan chan Subscription) (*TokenRouter, error) {
	return &TokenRouter{
		client:         client,
		SubChan:        subChan,
		UnSubChan:      unSubChan,
		tokenSubs:      make(map[string][]Subscription),
		allSubs:        make(map[uint64]Subscription),
		msgCh:          make(chan rueidis.PubSubMessage, 10000),
		channelCancels: make(map[string]context.CancelFunc),
	}, nil
}

func (tr *TokenRouter) Run(ctx context.Context) {
	defer func() {
		for _, cancel := range tr.channelCancels {
			cancel()
		}
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
				tr.subscribeChannel(ctx, token)
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
				tr.unsubscribeChannel(token)
			}

		case msg := <-tr.msgCh:
			metrics.RedisMessagesReceivedTotal.Inc()

			var pse PubSubEvent
			if err := pse.UnmarshalJSON([]byte(msg.Message)); err != nil {
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

// subscribeChannel starts a background Receive goroutine for a channel.
// On connection failure, it retries with exponential backoff.
// On intentional cancellation, it sends SUNSUBSCRIBE to clean up server-side.
func (tr *TokenRouter) subscribeChannel(ctx context.Context, token string) {
	chCtx, chCancel := context.WithCancel(ctx)
	tr.channelCancels[token] = chCancel
	ch := channelName(token)

	go func() {
		defer func() {
			cleanupCtx, cleanupCancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cleanupCancel()
			_ = tr.client.Do(cleanupCtx, tr.client.B().Sunsubscribe().Channel(ch).Build()).Error()
		}()

		backoff := 100 * time.Millisecond
		const maxBackoff = 10 * time.Second

		for {
			err := tr.client.Receive(chCtx, tr.client.B().Ssubscribe().Channel(ch).Build(), func(msg rueidis.PubSubMessage) {
				select {
				case tr.msgCh <- msg:
				default:
					metrics.RedisReceiveDropsTotal.Inc()
				}
			})

			if chCtx.Err() != nil {
				return
			}

			if err != nil {
				log.Printf("redis receive %s: %v (retrying in %s)", token, err, backoff)
				metrics.RedisErrors.WithLabelValues("receive").Inc()
			}

			select {
			case <-chCtx.Done():
				return
			case <-time.After(backoff):
			}

			backoff = min(backoff*2, maxBackoff)
		}
	}()

	metrics.RedisSubscribeTotal.Inc()
}

// unsubscribeChannel cancels the Receive goroutine for a channel.
func (tr *TokenRouter) unsubscribeChannel(token string) {
	if cancel, ok := tr.channelCancels[token]; ok {
		cancel()
		delete(tr.channelCancels, token)
		metrics.RedisSubscribeTotal.Dec()
	}
}
