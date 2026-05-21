package events

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"strconv"
	"time"

	"github.com/confluentinc/confluent-kafka-go/v2/kafka"
	jlexer "github.com/mailru/easyjson/jlexer"
	jwriter "github.com/mailru/easyjson/jwriter"
	"github.com/posthog/posthog/livestream/bot"
	"github.com/posthog/posthog/livestream/configs"
	"github.com/posthog/posthog/livestream/geo"
	"github.com/posthog/posthog/livestream/metrics"
	"github.com/prometheus/client_golang/prometheus"
)

// FlexibleString handles JSON values that can be either a string or a number,
// converting them to a string representation. This is needed because some SDKs
// (e.g., posthog-ruby) may send distinct_id as an integer instead of a string.
type FlexibleString string

func (f *FlexibleString) UnmarshalEasyJSON(in *jlexer.Lexer) {
	if in.IsNull() {
		in.Skip()
		*f = ""
		return
	}

	// Try to detect the type by looking at the first character
	data := in.Raw()
	if len(data) == 0 {
		*f = ""
		return
	}

	// If it starts with a quote, it's a string
	if data[0] == '"' {
		var s string
		if err := json.Unmarshal(data, &s); err != nil {
			in.AddError(err)
			return
		}
		*f = FlexibleString(s)
		return
	}

	// Otherwise, try to parse as a number and convert to string
	var n json.Number
	if err := json.Unmarshal(data, &n); err != nil {
		// If that fails, just use the raw value as a string
		*f = FlexibleString(string(data))
		return
	}
	*f = FlexibleString(n.String())
}

func (f FlexibleString) MarshalEasyJSON(out *jwriter.Writer) {
	out.String(string(f))
}

func (f *FlexibleString) UnmarshalJSON(data []byte) error {
	if len(data) == 0 || string(data) == "null" {
		*f = ""
		return nil
	}

	// If it starts with a quote, it's a string
	if data[0] == '"' {
		var s string
		if err := json.Unmarshal(data, &s); err != nil {
			return err
		}
		*f = FlexibleString(s)
		return nil
	}

	// Otherwise, try to parse as a number and convert to string
	var n json.Number
	if err := json.Unmarshal(data, &n); err != nil {
		return fmt.Errorf("FlexibleString: cannot unmarshal %s", string(data))
	}
	*f = FlexibleString(n.String())
	return nil
}

func (f FlexibleString) MarshalJSON() ([]byte, error) {
	return json.Marshal(string(f))
}

//easyjson:json
type PostHogEventWrapper struct {
	Uuid       string         `json:"uuid"`
	DistinctId FlexibleString `json:"distinct_id"`
	Ip         string         `json:"ip"`
	Data       string         `json:"data"`
	Token      string         `json:"token"`
	Timestamp  string         `json:"timestamp"`
}

//easyjson:json
type PostHogEvent struct {
	Token      string                 `json:"api_key,omitempty"`
	Event      string                 `json:"event"`
	Properties map[string]interface{} `json:"properties"`
	Timestamp  interface{}            `json:"timestamp,omitempty"`

	Uuid        string
	DistinctId  string
	Lat         float64
	Lng         float64
	CountryCode string

	// Bot classification (populated by bot.Classifier)
	IsBot           bool
	TrafficType     string
	TrafficCategory string
	BotName         string
}

type KafkaConsumerInterface interface {
	SubscribeTopics(topics []string, rebalanceCb kafka.RebalanceCb) error
	ReadMessage(timeout time.Duration) (*kafka.Message, error)
	Close() error
}

type PostHogKafkaConsumer struct {
	consumer       KafkaConsumerInterface
	topic          string
	geolocator     geo.GeoLocator
	botClassifier  *bot.Classifier
	incoming       chan []byte
	outgoingChan   chan PostHogEvent
	statsChan      chan CountEvent
	parallel       int
	Broker         *RedisEventBroker
}

func NewPostHogKafkaConsumer(
	consumerConfig configs.ConsumerConfig,
	geolocator geo.GeoLocator,
	outgoingChan chan PostHogEvent, statsChan chan CountEvent, parallel int) (*PostHogKafkaConsumer, error) {

	config := &kafka.ConfigMap{
		"bootstrap.servers":          consumerConfig.Brokers,
		"group.id":                   consumerConfig.GroupID,
		"auto.offset.reset":          "latest",
		"enable.auto.commit":         false,
		"security.protocol":          consumerConfig.SecurityProtocol,
		"fetch.message.max.bytes":    1_000_000_000,
		"fetch.max.bytes":            1_000_000_000,
		"queued.max.messages.kbytes": 2_000_000,
	}
	applyKafkaConfigOverrides(config, consumerConfig)

	consumer, err := kafka.NewConsumer(config)
	if err != nil {
		return nil, err
	}

	return &PostHogKafkaConsumer{
		consumer:      consumer,
		topic:         consumerConfig.Topic,
		geolocator:    geolocator,
		botClassifier: bot.NewClassifier(),
		incoming:      make(chan []byte, (1+parallel)*100),
		outgoingChan:  outgoingChan,
		statsChan:     statsChan,
		parallel:      parallel,
	}, nil
}

func (c *PostHogKafkaConsumer) Consume(ctx context.Context) {
	rebalanceCallback := func(consumer *kafka.Consumer, event kafka.Event) error {
		if _, ok := event.(kafka.AssignedPartitions); ok {
			log.Printf("✅ Livestream service ready")
		}
		return nil
	}

	if err := c.consumer.SubscribeTopics([]string{c.topic}, rebalanceCallback); err != nil {
		log.Fatalf("Failed to subscribe to topic: %v", err)
	}

	for i := 0; i < c.parallel; i++ {
		go c.runParsing(ctx)
	}

	for {
		msg, err := c.consumer.ReadMessage(15 * time.Second)
		if err != nil {
			var inErr kafka.Error
			if errors.As(err, &inErr) {
				if inErr.Code() == kafka.ErrTransport {
					metrics.ConnectFailure.Inc()
				} else if inErr.IsTimeout() {
					metrics.TimeoutConsume.Inc()
					continue
				}
			}
			log.Printf("Error consuming message: %v", err)
			// TODO capture error to PostHog
			continue
		}

		metrics.MsgConsumed.With(prometheus.Labels{"partition": strconv.Itoa(int(msg.TopicPartition.Partition))}).Inc()
		c.incoming <- msg.Value
	}
}

func (c *PostHogKafkaConsumer) runParsing(ctx context.Context) {
	for {
		value, ok := <-c.incoming
		if !ok {
			return
		}
		phEvent := parse(c.geolocator, c.botClassifier, value)
		if phEvent.Token == "" {
			continue
		}
		c.statsChan <- CountEvent{Token: phEvent.Token, DistinctID: phEvent.DistinctId}
		if c.Broker != nil {
			c.Broker.Publish(ctx, phEvent)
		} else {
			c.outgoingChan <- phEvent
		}
	}
}

func parse(geolocator geo.GeoLocator, classifier *bot.Classifier, kafkaMessage []byte) PostHogEvent {
	var wrapperMessage PostHogEventWrapper
	if err := json.Unmarshal(kafkaMessage, &wrapperMessage); err != nil {
		log.Printf("Error decoding JSON %s: %v", err, string(kafkaMessage))
	}

	if wrapperMessage.Timestamp != "" {
		if eventTime, err := time.Parse(time.RFC3339Nano, wrapperMessage.Timestamp); err == nil {
			if lag := time.Since(eventTime).Seconds(); lag >= 0 {
				metrics.EventLagHistogram.Observe(lag)
			}
		}
	}

	phEvent := PostHogEvent{
		Timestamp:  wrapperMessage.Timestamp,
		Token:      "",
		Event:      "",
		Properties: make(map[string]interface{}),
	}

	data := []byte(wrapperMessage.Data)
	if err := json.Unmarshal(data, &phEvent); err != nil {
		log.Printf("Error decoding JSON %s: %v", err, string(data))
	}

	phEvent.Uuid = wrapperMessage.Uuid
	phEvent.DistinctId = string(wrapperMessage.DistinctId)

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
		geoResult, err := geolocator.Lookup(ipStr)
		if err != nil {
			metrics.GeoIPLookupFailures.Inc()
		}
		phEvent.Lat = geoResult.Latitude
		phEvent.Lng = geoResult.Longitude
		phEvent.CountryCode = geoResult.CountryCode
	}

	if classifier != nil && shouldClassifyBot(phEvent.Event) {
		userAgent := extractUserAgent(phEvent.Properties)
		if userAgent != "" {
			result := classifier.Classify(userAgent)
			phEvent.IsBot = result.IsBot
			phEvent.TrafficType = result.TrafficType
			phEvent.TrafficCategory = result.TrafficCategory
			phEvent.BotName = result.BotName
			// Inject $virt_* properties so they flow through both the
			// in-memory filter and the Redis pub/sub path.
			if result.TrafficType != "" {
				phEvent.Properties["$virt_is_bot"] = result.IsBot
				phEvent.Properties["$virt_traffic_type"] = result.TrafficType
				phEvent.Properties["$virt_traffic_category"] = result.TrafficCategory
				if result.BotName != "" {
					phEvent.Properties["$virt_bot_name"] = result.BotName
				}
			}
		}
	}

	return phEvent
}

var botClassifyEvents = map[string]bool{
	"$pageview":  true,
	"$pageleave": true,
	"$screen":    true,
	"$http_log":  true,
	"$autocapture": true,
}

func shouldClassifyBot(event string) bool {
	return botClassifyEvents[event]
}

func extractUserAgent(props map[string]interface{}) string {
	if uaValue, ok := props["$user_agent"]; ok {
		if ua, ok := uaValue.(string); ok && ua != "" {
			return ua
		}
	}
	if rawUA, ok := props["$raw_user_agent"]; ok {
		if ua, ok := rawUA.(string); ok && ua != "" {
			return ua
		}
	}
	return ""
}

func (c *PostHogKafkaConsumer) Close() {
	if err := c.consumer.Close(); err != nil {
		// TODO capture error to PostHog
		log.Printf("Failed to close consumer: %v", err)
	}
	close(c.incoming)
}

func (c *PostHogKafkaConsumer) IncomingRatio() float64 {
	return float64(len(c.incoming)) / float64(cap(c.incoming))
}

func applyKafkaConfigOverrides(config *kafka.ConfigMap, consumerConfig configs.ConsumerConfig) {
	if consumerConfig.ClientID != "" {
		_ = config.SetKey("client.id", consumerConfig.ClientID)
	}
	if consumerConfig.SessionTimeoutMs > 0 {
		_ = config.SetKey("session.timeout.ms", consumerConfig.SessionTimeoutMs)
	}
	if consumerConfig.HeartbeatIntervalMs > 0 {
		_ = config.SetKey("heartbeat.interval.ms", consumerConfig.HeartbeatIntervalMs)
	}
	if consumerConfig.MaxPollIntervalMs > 0 {
		_ = config.SetKey("max.poll.interval.ms", consumerConfig.MaxPollIntervalMs)
	}
}
