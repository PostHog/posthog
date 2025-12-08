package events

import (
	"context"
	"errors"
	"log"
	"strconv"
	"time"

	"github.com/confluentinc/confluent-kafka-go/v2/kafka"
	"github.com/posthog/posthog/livestream/metrics"
	"github.com/prometheus/client_golang/prometheus"
)

type SessionRecordingEvent struct {
	Token     string
	SessionId string
}

type SessionRecordingKafkaConsumer struct {
	consumer  KafkaConsumerInterface
	topic     string
	statsChan chan SessionRecordingEvent
}

func NewSessionRecordingKafkaConsumer(
	brokers string, securityProtocol string, groupID string, topic string,
	statsChan chan SessionRecordingEvent) (*SessionRecordingKafkaConsumer, error) {

	config := &kafka.ConfigMap{
		"bootstrap.servers":          brokers,
		"group.id":                   groupID + "-session-recordings",
		"auto.offset.reset":          "latest",
		"enable.auto.commit":         false,
		"security.protocol":          securityProtocol,
		"fetch.message.max.bytes":    10_000_000,  // 10MB - we only read headers
		"fetch.max.bytes":            50_000_000,  // 50MB - reduced from 1GB
		"queued.max.messages.kbytes": 100_000,     // 100MB - reduced from 2GB
	}

	consumer, err := kafka.NewConsumer(config)
	if err != nil {
		return nil, err
	}

	return &SessionRecordingKafkaConsumer{
		consumer:  consumer,
		topic:     topic,
		statsChan: statsChan,
	}, nil
}

func (c *SessionRecordingKafkaConsumer) Consume(ctx context.Context) {
	if err := c.consumer.SubscribeTopics([]string{c.topic}, nil); err != nil {
		log.Fatalf("Failed to subscribe to session recording topic: %v", err)
	}

	for {
		select {
		case <-ctx.Done():
			log.Println("session recording consumer shutting down...")
			return
		default:
			msg, err := c.consumer.ReadMessage(1 * time.Second)
			if err != nil {
				var inErr kafka.Error
				if errors.As(err, &inErr) {
					if inErr.Code() == kafka.ErrTransport {
						metrics.SessionRecordingConnectFailure.Inc()
					} else if inErr.IsTimeout() {
						metrics.SessionRecordingTimeoutConsume.Inc()
						continue
					}
				}
				log.Printf("Error consuming session recording message: %v", err)
				continue
			}

			metrics.SessionRecordingMsgConsumed.With(prometheus.Labels{"partition": strconv.Itoa(int(msg.TopicPartition.Partition))}).Inc()

			token, sessionId := parseSessionRecordingHeaders(msg.Headers)
			if token != "" && sessionId != "" {
				select {
				case c.statsChan <- SessionRecordingEvent{Token: token, SessionId: sessionId}:
				case <-ctx.Done():
					return
				}
			} else {
				metrics.SessionRecordingDroppedMessages.Inc()
			}
		}
	}
}

func parseSessionRecordingHeaders(headers []kafka.Header) (token, sessionId string) {
	for _, h := range headers {
		switch h.Key {
		case "token":
			token = string(h.Value)
		case "session_id":
			sessionId = string(h.Value)
		}
	}
	return
}

func (c *SessionRecordingKafkaConsumer) Close() {
	if err := c.consumer.Close(); err != nil {
		log.Printf("Failed to close session recording consumer: %v", err)
	}
}
