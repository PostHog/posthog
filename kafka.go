package main

import (
	"encoding/json"
	"log"
	"time"

	"github.com/confluentinc/confluent-kafka-go/v2/kafka"
)

type PostHogEventWrapper struct {
	Uuid       string `json:"uuid"`
	DistinctId string `json:"distinct_id"`
	Ip         string `json:"ip"`
	Data       string `json:"data"`
}

type PostHogEvent struct {
	Token      string                 `json:"api_key,omitempty"`
	Event      string                 `json:"event"`
	Properties map[string]interface{} `json:"properties"`
	Timestamp  string                 `json:"timestamp,omitempty"`

	Uuid       string
	DistinctId string
	Lat        float64
	Lng        float64
}

type KafkaConsumer struct {
	consumer     *kafka.Consumer
	topic        string
	geolocator   *GeoLocator
	outgoingChan chan PostHogEvent
	statsChan    chan PostHogEvent
}

func NewKafkaConsumer(brokers string, securityProtocol string, groupID string, topic string, geolocator *GeoLocator, outgoingChan chan PostHogEvent, statsChan chan PostHogEvent) (*KafkaConsumer, error) {
	config := &kafka.ConfigMap{
		"bootstrap.servers":  brokers,
		"group.id":           groupID,
		"auto.offset.reset":  "latest",
		"enable.auto.commit": false,
		"security.protocol":  securityProtocol,
	}

	consumer, err := kafka.NewConsumer(config)
	if err != nil {
		return nil, err
	}

	return &KafkaConsumer{
		consumer:     consumer,
		topic:        topic,
		geolocator:   geolocator,
		outgoingChan: outgoingChan,
		statsChan:    statsChan,
	}, nil
}

func (c *KafkaConsumer) Consume() {
	err := c.consumer.SubscribeTopics([]string{c.topic}, nil)
	if err != nil {
		log.Fatalf("Failed to subscribe to topic: %v", err)
	}

	for {
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

		var phEvent PostHogEvent
		err = json.Unmarshal([]byte(wrapperMessage.Data), &phEvent)
		if err != nil {
			log.Printf("Error decoding JSON: %v", err)
			continue
		}

		phEvent.Uuid = wrapperMessage.Uuid
		phEvent.DistinctId = wrapperMessage.DistinctId
		if phEvent.Timestamp == "" {
			phEvent.Timestamp = time.Now().UTC().Format("2006-01-02T15:04:05.000Z")
		}
		if phEvent.Token == "" {
			if tokenValue, ok := phEvent.Properties["token"].(string); ok {
				phEvent.Token = tokenValue
			}
		}

		var ipStr string = ""
		if ipValue, ok := phEvent.Properties["$ip"]; ok {
			if ipProp, ok := ipValue.(string); ok {
				if ipProp != "" {
					ipStr = ipProp
				}
			}
		} else {
			if wrapperMessage.Ip != "" {
				ipStr = wrapperMessage.Ip
			}
		}

		if ipStr != "" {
			phEvent.Lat, phEvent.Lng = c.geolocator.Lookup(ipStr)
		}

		c.outgoingChan <- phEvent
		c.statsChan <- phEvent
	}
}

func (c *KafkaConsumer) Close() {
	c.consumer.Close()
}
