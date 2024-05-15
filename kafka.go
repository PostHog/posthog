package main

import (
	"encoding/json"
	"fmt"
	"log"

	"github.com/confluentinc/confluent-kafka-go/v2/kafka"
)

type PostHogEvent struct {
	Token      string                 `json:"token,omitempty"`
	DistinctID interface{}            `json:"distinct_id,omitempty"`
	Event      string                 `json:"event"`
	Properties map[string]interface{} `json:"properties"`
	Timestamp  string                 `json:"timestamp,omitempty"`
}

type KafkaConsumer struct {
	consumer *kafka.Consumer
	topic    string
}

func NewKafkaConsumer(brokers string, groupID string, topic string) (*KafkaConsumer, error) {
	config := &kafka.ConfigMap{
		"bootstrap.servers":  brokers,
		"group.id":           groupID,
		"auto.offset.reset":  "latest",
		"enable.auto.commit": false,
		"security.protocol":  "SSL",
	}

	consumer, err := kafka.NewConsumer(config)
	if err != nil {
		return nil, err
	}

	return &KafkaConsumer{
		consumer: consumer,
		topic:    topic,
	}, nil
}

func (c *KafkaConsumer) Consume() {
	err := c.consumer.SubscribeTopics([]string{c.topic}, nil)
	if err != nil {
		log.Fatalf("Failed to subscribe to topic: %v", err)
	}

	i := 0
	for {
		msg, err := c.consumer.ReadMessage(-1)
		if err != nil {
			log.Printf("Error consuming message: %v", err)
			continue
		}

		var message PostHogEvent
		err = json.Unmarshal(msg.Value, &message)
		if err != nil {
			log.Printf("Error decoding JSON: %v", err)
			continue
		}

		i += 1
		if i%1000 == 0 {
			fmt.Printf("Received message: Token=%s, DistinctID=%s\n", message.Token, message.DistinctID)
		}
	}
}

func (c *KafkaConsumer) Close() {
	c.consumer.Close()
}
