package events

import (
	"context"
	"fmt"
	"log"
	"slices"
	"sync"
	"time"

	"github.com/posthog/posthog/livestream/configs"
	"github.com/posthog/posthog/livestream/metrics"
	"github.com/redis/rueidis"
)

func channelName(token string) string {
	return fmt.Sprintf("livestream:events:%s", token)
}

type RedisEventBroker struct {
	client     rueidis.Client
	publishCh  chan PostHogEvent
	numWorkers int
}

func NewRedisEventBroker(cfg configs.RedisConfig) (*RedisEventBroker, error) {
	client, err := newRedisClient(cfg)
	if err != nil {
		return nil, err
	}
	return &RedisEventBroker{
		client:     client,
		publishCh:  make(chan PostHogEvent, cfg.PublishBufferSize),
		numWorkers: cfg.PublishWorkers,
	}, nil
}

func NewRedisEventBrokerFromClient(client rueidis.Client, bufferSize, numWorkers int) *RedisEventBroker {
	return &RedisEventBroker{
		client:     client,
		publishCh:  make(chan PostHogEvent, bufferSize),
		numWorkers: numWorkers,
	}
}

// Publish enqueues an event for async publishing to Redis. Non-blocking, drops and emits a metric if buffer is full.
func (b *RedisEventBroker) Publish(ctx context.Context, event PostHogEvent) {
	if event.Token == "" {
		return
	}
	select {
	case b.publishCh <- event:
	default:
		metrics.RedisPublishDropsTotal.Inc()
	}
}

// Run starts the publish worker pool and blocks until ctx is cancelled.
func (b *RedisEventBroker) Run(ctx context.Context) {
	var wg sync.WaitGroup
	for i := 0; i < b.numWorkers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			b.publishWorker(ctx)
		}()
	}
	wg.Wait()
}

func (b *RedisEventBroker) publishWorker(ctx context.Context) {
	for {
		select {
		case <-ctx.Done():
			return
		case event := <-b.publishCh:
			b.doPublish(ctx, event)
		}
	}
}

func (b *RedisEventBroker) doPublish(ctx context.Context, event PostHogEvent) {
	data, err := event.MarshalJSON()
	if err != nil {
		log.Printf("redis publish: marshal error: %v", err)
		metrics.RedisPublishErrorsTotal.Inc()
		return
	}

	if err := b.client.Do(ctx, b.client.B().Spublish().Channel(channelName(event.Token)).Message(string(data)).Build()).Error(); err != nil {
		if ctx.Err() == nil {
			log.Printf("redis publish failed for distinct id %s", event.DistinctId)
			metrics.RedisPublishErrorsTotal.Inc()
		}
		return
	}

	metrics.RedisPublishTotal.Inc()
}

// BufferRatio returns the fraction of the publish buffer currently in use.
func (b *RedisEventBroker) BufferRatio() float64 {
	return float64(len(b.publishCh)) / float64(cap(b.publishCh))
}

func (b *RedisEventBroker) Close() {
	b.client.Close()
}

func NewRedisClient(cfg configs.RedisConfig) (rueidis.Client, error) {
	return newRedisClient(cfg)
}

// TokenRouter manages per-token Redis sharded pub/sub subscriptions, fanning out received messages to SSE subscribers.
type TokenRouter struct {
	client         rueidis.Client
	SubChan        chan Subscription
	UnSubChan      chan Subscription
	tokenSubs      map[string][]Subscription
	allSubs        map[uint64]Subscription
	msgCh          chan rueidis.PubSubMessage
	channelCancels map[string]context.CancelFunc
}

func NewTokenRouter(client rueidis.Client, subChan, unSubChan chan Subscription) *TokenRouter {
	return &TokenRouter{
		client:         client,
		SubChan:        subChan,
		UnSubChan:      unSubChan,
		tokenSubs:      make(map[string][]Subscription),
		allSubs:        make(map[uint64]Subscription),
		msgCh:          make(chan rueidis.PubSubMessage, 10000),
		channelCancels: make(map[string]context.CancelFunc),
	}
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
			logUnsubscribe(sub)

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

			var event PostHogEvent
			if err := event.UnmarshalJSON([]byte(msg.Message)); err != nil {
				log.Printf("redis message unmarshal: %v", err)
				continue
			}

			subs := tr.tokenSubs[event.Token]
			deliverEvent(event, subs)
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

		const (
			initialBackoff = 100 * time.Millisecond
			maxBackoff     = 10 * time.Second
		)
		backoff := initialBackoff

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
				select {
				case <-chCtx.Done():
					return
				case <-time.After(backoff):
				}
				backoff = min(backoff*2, maxBackoff)
			} else {
				backoff = initialBackoff
			}
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
