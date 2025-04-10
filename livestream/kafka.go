package main

import (
	"encoding/json"
	"errors"
	"log"
	"time"

	"github.com/confluentinc/confluent-kafka-go/v2/kafka"
	"github.com/getsentry/sentry-go"
)

type PostHogEventWrapper struct {
	Uuid       string `json:"uuid"`
	DistinctId string `json:"distinct_id"`
	Ip         string `json:"ip"`
	Data       string `json:"data"`
	Token      string `json:"token"`
}

type PostHogEvent struct {
	Token      string                 `json:"api_key,omitempty"`
	Event      string                 `json:"event"`
	Properties map[string]interface{} `json:"properties"`
	Timestamp  interface{}            `json:"timestamp,omitempty"`

	Uuid       string
	DistinctId string
	Lat        float64
	Lng        float64
}

type KafkaConsumerInterface interface {
	SubscribeTopics(topics []string, rebalanceCb kafka.RebalanceCb) error
	ReadMessage(timeout time.Duration) (*kafka.Message, error)
	Close() error
}

type PostHogKafkaConsumer struct {
	consumer     KafkaConsumerInterface
	topic        string
	geolocator   GeoLocator
	outgoingChan chan PostHogEvent
	statsChan    chan CountEvent
}

func NewPostHogKafkaConsumer(
	brokers string, securityProtocol string, groupID string, topic string, geolocator GeoLocator,
	outgoingChan chan PostHogEvent, statsChan chan CountEvent) (*PostHogKafkaConsumer, error) {

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

	return &PostHogKafkaConsumer{
		consumer:     consumer,
		topic:        topic,
		geolocator:   geolocator,
		outgoingChan: outgoingChan,
		statsChan:    statsChan,
	}, nil
}

func (c *PostHogKafkaConsumer) Consume() {
	if err := c.consumer.SubscribeTopics([]string{c.topic}, nil); err != nil {
		sentry.CaptureException(err)
		log.Fatalf("Failed to subscribe to topic: %v", err)
	}

	for {
		msg, err := c.consumer.ReadMessage(15 * time.Second)
		if err != nil {
			var inErr kafka.Error
			if errors.As(err, &inErr) {
				if inErr.Code() == kafka.ErrTransport {
					connectFailure.Inc()
				} else if inErr.IsTimeout() {
					timeoutConsume.Inc()
					continue
				}
			}
			log.Printf("Error consuming message: %v", err)
			sentry.CaptureException(err)
			continue
		}

		msgConsumed.Inc()
		phEvent := parse(c.geolocator, msg.Value)

		c.outgoingChan <- phEvent
		c.statsChan <- CountEvent{Token: phEvent.Token, DistinctID: phEvent.DistinctId}
	}
}

func parse(geolocator GeoLocator, kafkaMessage []byte) PostHogEvent {
	var wrapperMessage PostHogEventWrapper
	if err := json.Unmarshal(kafkaMessage, &wrapperMessage); err != nil {
		log.Printf("Error decoding JSON %s: %v", err, string(kafkaMessage))
	}

	phEvent := PostHogEvent{
		Timestamp:  time.Now().UTC().Format("2006-01-02T15:04:05.000Z"),
		Token:      "",
		Event:      "",
		Properties: make(map[string]interface{}),
	}

	data := []byte(wrapperMessage.Data)
	if err := json.Unmarshal(data, &phEvent); err != nil {
		log.Printf("Error decoding JSON %s: %v", err, string(data))
	}

	phEvent.Uuid = wrapperMessage.Uuid
	phEvent.DistinctId = wrapperMessage.DistinctId

	if wrapperMessage.Token != "" {
		phEvent.Token = wrapperMessage.Token
	} else if phEvent.Token == "" {
		if tokenValue, ok := phEvent.Properties["token"].(string); ok {
			phEvent.Token = tokenValue
		} else {
			log.Printf("No valid token found in event with UUID: %s", wrapperMessage.Uuid)
		}
	}

	var ipStr = ""
	if ipValue, ok := phEvent.Properties["$ip"]; ok {
		if ipProp, ok := ipValue.(string); ok && ipProp != "" {
			ipStr = ipProp
		}
	} else if wrapperMessage.Ip != "" {
		ipStr = wrapperMessage.Ip
	}

	if ipStr != "" {
		var err error
		phEvent.Lat, phEvent.Lng, err = geolocator.Lookup(ipStr)
		if err != nil && err.Error() != "invalid IP address" { // An invalid IP address is not an error on our side
			sentry.CaptureException(err)
		}
	}

	return phEvent
}

func (c *PostHogKafkaConsumer) Close() {
	c.consumer.Close()
}
