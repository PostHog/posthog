package main

import (
	"encoding/json"
	"fmt"
	"log"

	"github.com/confluentinc/confluent-kafka-go/v2/kafka"
)

type PostHogEventWrapper struct {
	Data string `json:"data"`
}

type PostHogEvent struct {
	Token      string                 `json:"token,omitempty"`
	DistinctID interface{}            `json:"distinct_id,omitempty"`
	Event      string                 `json:"event"`
	Properties map[string]interface{} `json:"properties"`
	Timestamp  string                 `json:"timestamp,omitempty"`
}

type KafkaConsumer struct {
	consumer   *kafka.Consumer
	topic      string
	geolocator *GeoLocator
}

func NewKafkaConsumer(brokers string, groupID string, topic string, geolocator *GeoLocator) (*KafkaConsumer, error) {
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
		consumer:   consumer,
		topic:      topic,
		geolocator: geolocator,
	}, nil
}

func (c *KafkaConsumer) Consume() {
	err := c.consumer.SubscribeTopics([]string{c.topic}, nil)
	if err != nil {
		log.Fatalf("Failed to subscribe to topic: %v", err)
	}

	i := 0
	for {
		i += 1

		msg, err := c.consumer.ReadMessage(-1)
		if err != nil {
			log.Printf("Error consuming message: %v", err)
			continue
		}

		var wrapperMessage PostHogEventWrapper
		err = json.Unmarshal(msg.Value, &wrapperMessage)
		if err != nil {
			log.Printf("Error decoding JSON: %v", err)
			continue
		}

		if i%10000 == 0 {
			fmt.Printf("datamsg: %v\n", string(msg.Value))
		}

		var message PostHogEvent
		err = json.Unmarshal([]byte(wrapperMessage.Data), &message)
		if err != nil {
			log.Printf("Error decoding JSON: %v", err)
			continue
		}

		lat, lng := 0.0, 0.0
		if ipValue, ok := message.Properties["$ip"]; ok {
			if ipStr, ok := ipValue.(string); ok {
				if ipStr != "" {
					lat, lng = c.geolocator.Lookup(ipStr)
				}

			}
		}

		if i%10000 == 0 {
			fmt.Printf("Received message: Token=%s, DistinctID=%s Lat=%f Lng=%f Property Count=%v\n", message.Token, message.DistinctID, lat, lng, len(message.Properties))
		}
	}
}

func (c *KafkaConsumer) Close() {
	c.consumer.Close()
}
