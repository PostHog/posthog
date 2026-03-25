package events

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"time"

	"github.com/confluentinc/confluent-kafka-go/v2/kafka"
	"github.com/posthog/posthog/livestream/configs"
	"github.com/posthog/posthog/livestream/metrics"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/redis/rueidis"
)

type NotificationKafkaConsumer struct {
	consumer    KafkaConsumerInterface
	topic       string
	redisClient rueidis.Client
}

func NewNotificationKafkaConsumer(
	kafkaConfig configs.KafkaConfig, redisClient rueidis.Client,
) (*NotificationKafkaConsumer, error) {
	config := &kafka.ConfigMap{
		"bootstrap.servers":  kafkaConfig.Brokers,
		"group.id":           kafkaConfig.GroupID + "-notifications",
		"auto.offset.reset":  "latest",
		"enable.auto.commit": false,
		"security.protocol":  kafkaConfig.SecurityProtocol,
	}

	applyKafkaConfigOverrides(config, kafkaConfig)

	consumer, err := kafka.NewConsumer(config)
	if err != nil {
		return nil, err
	}

	return &NotificationKafkaConsumer{
		consumer:    consumer,
		topic:       kafkaConfig.NotificationTopic,
		redisClient: redisClient,
	}, nil
}

func (c *NotificationKafkaConsumer) Consume(ctx context.Context) {
	if err := c.consumer.SubscribeTopics([]string{c.topic}, nil); err != nil {
		log.Printf("Failed to subscribe to notification topic: %v", err)
		return
	}
	log.Printf("Notification consumer subscribed to topic: %s", c.topic)

	for {
		select {
		case <-ctx.Done():
			return
		default:
		}

		msg, err := c.consumer.ReadMessage(5 * time.Second)
		if err != nil {
			if kafkaErr, ok := err.(kafka.Error); ok && kafkaErr.IsTimeout() {
				continue
			}
			log.Printf("Error consuming notification message: %v", err)
			continue
		}

		c.processMessage(ctx, msg.Value)
	}
}

func (c *NotificationKafkaConsumer) processMessage(ctx context.Context, value []byte) {
	var data struct {
		OrganizationID string `json:"organization_id"`
	}
	if err := json.Unmarshal(value, &data); err != nil {
		metrics.NotificationErrors.With(prometheus.Labels{"reason": "invalid_json"}).Inc()
		return
	}
	if data.OrganizationID == "" {
		metrics.NotificationErrors.With(prometheus.Labels{"reason": "missing_organization_id"}).Inc()
		return
	}

	channel := fmt.Sprintf("notifications:%s", data.OrganizationID)
	cmd := c.redisClient.B().Spublish().Channel(channel).Message(string(value)).Build()
	if err := c.redisClient.Do(ctx, cmd).Error(); err != nil {
		log.Printf("Failed to publish notification to Redis: %v", err)
	}
}

func (c *NotificationKafkaConsumer) Close() {
	_ = c.consumer.Close()
}
