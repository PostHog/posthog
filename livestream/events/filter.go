package events

import (
	"fmt"
	"log"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"sync/atomic"

	"github.com/gofrs/uuid/v5"
	"github.com/posthog/posthog/livestream/auth"
	"github.com/posthog/posthog/livestream/metrics"
	"github.com/prometheus/client_golang/prometheus"
)

const (
	OpExact        = "exact"
	OpIsNot        = "is_not"
	OpIContains    = "icontains"
	OpNotIContains = "not_icontains"
	OpRegex        = "regex"
	OpNotRegex     = "not_regex"
	OpGreaterThan  = "gt"
	OpGreaterEqual = "gte"
	OpLessThan     = "lt"
	OpLessEqual    = "lte"
	OpIsSet        = "is_set"
	OpIsNotSet     = "is_not_set"
)

type CompiledPropertyFilter struct {
	Key      string
	Operator string
	Values   []string

	lowerValues []string
	regexes     []*regexp.Regexp
	numbers     []float64
	numericOK   []bool
}

func NewCompiledPropertyFilter(key, operator string, values []string) CompiledPropertyFilter {
	f := CompiledPropertyFilter{Key: key, Operator: operator, Values: values}
	switch operator {
	case OpIContains, OpNotIContains:
		f.lowerValues = make([]string, len(values))
		for i, v := range values {
			f.lowerValues[i] = strings.ToLower(v)
		}
	case OpRegex, OpNotRegex:
		f.regexes = make([]*regexp.Regexp, len(values))
		for i, v := range values {
			if re, err := regexp.Compile(v); err == nil {
				f.regexes[i] = re
			} else {
				log.Printf("WARNING: ignoring invalid regex in %s filter for key=%s value=%q: %v", operator, key, v, err)
			}
		}
	case OpGreaterThan, OpGreaterEqual, OpLessThan, OpLessEqual:
		f.numbers = make([]float64, len(values))
		f.numericOK = make([]bool, len(values))
		for i, v := range values {
			if n, err := strconv.ParseFloat(strings.TrimSpace(v), 64); err == nil {
				f.numbers[i] = n
				f.numericOK[i] = true
			}
		}
	}
	return f
}

type Subscription struct {
	SubID uint64

	// Filters
	TeamId          int
	Token           string
	DistinctId      string
	EventTypes      []string
	PropertyFilters []CompiledPropertyFilter

	Geo     bool
	Columns []string

	// Swapped by the handler on every authorization re-check; nil restricts nothing.
	Restrictions *atomic.Pointer[auth.PropertyRestrictions]

	// Transformations
	PathCleaner *PathCleaner

	// Channels
	EventChan   chan interface{}
	ShouldClose *atomic.Bool

	// Stats
	DroppedEvents *atomic.Uint64
}

//easyjson:json
type ResponsePostHogEvent struct {
	Uuid       string                 `json:"uuid"`
	Timestamp  interface{}            `json:"timestamp"`
	DistinctId string                 `json:"distinct_id"`
	PersonId   string                 `json:"person_id"`
	Event      string                 `json:"event"`
	Properties map[string]interface{} `json:"properties"`
}

//easyjson:json
type ResponseGeoEvent struct {
	Lat         float64 `json:"lat"`
	Lng         float64 `json:"lng"`
	CountryCode string  `json:"country_code"`
	DistinctId  string  `json:"distinct_id"`
	Count       uint    `json:"count"`
}

type Filter struct {
	inboundChan chan PostHogEvent
	SubChan     chan Subscription
	UnSubChan   chan Subscription
	subs        []Subscription
}

func NewFilter(subChan chan Subscription, unSubChan chan Subscription, inboundChan chan PostHogEvent) *Filter {
	return &Filter{SubChan: subChan, UnSubChan: unSubChan, inboundChan: inboundChan, subs: make([]Subscription, 0)}
}

func convertToResponseGeoEvent(event PostHogEvent) *ResponseGeoEvent {
	return &ResponseGeoEvent{
		Lat:         event.Lat,
		Lng:         event.Lng,
		CountryCode: event.CountryCode,
		DistinctId:  event.DistinctId,
		Count:       1,
	}
}

// Person properties ride along on events under these keys, so a restricted
// person property has to be removed from inside them as well.
var personPropertyContainers = []string{"$set", "$set_once"}

func (s *Subscription) restrictions() *auth.PropertyRestrictions {
	if s.Restrictions == nil {
		return nil
	}
	return s.Restrictions.Load()
}

// A filter on a hidden key would let the subscriber infer its values from which events match.
func RestrictedFilterKey(filters []CompiledPropertyFilter, restrictions *auth.PropertyRestrictions) string {
	for i := range filters {
		if restrictions.RestrictsEventProperty(filters[i].Key) {
			return filters[i].Key
		}
	}
	return ""
}

func visibleProperty(key string, value interface{}, restrictions *auth.PropertyRestrictions) (interface{}, bool) {
	if restrictions.RestrictsEventProperty(key) {
		return nil, false
	}
	if !restrictions.HasPersonRestrictions() || !slices.Contains(personPropertyContainers, key) {
		return value, true
	}
	nested, ok := value.(map[string]interface{})
	if !ok {
		return value, true
	}
	stripped := make(map[string]interface{}, len(nested))
	for k, v := range nested {
		if !restrictions.RestrictsPersonProperty(k) {
			stripped[k] = v
		}
	}
	return stripped, true
}

func convertToResponsePostHogEvent(
	event PostHogEvent,
	teamId int,
	columns []string,
	pathCleaner *PathCleaner,
	restrictions *auth.PropertyRestrictions,
) *ResponsePostHogEvent {
	var properties map[string]interface{}
	if columns == nil {
		properties = event.Properties
		if pathCleaner != nil || restrictions != nil {
			// About to inject or remove per-subscriber properties; copy so the
			// shared event map never carries one subscription's view into another.
			properties = make(map[string]interface{}, len(event.Properties)+1)
			for k, v := range event.Properties {
				if visible, ok := visibleProperty(k, v, restrictions); ok {
					properties[k] = visible
				}
			}
		}
	} else {
		properties = make(map[string]interface{})
		for _, key := range columns {
			if val, ok := event.Properties[key]; ok {
				if visible, ok := visibleProperty(key, val, restrictions); ok {
					properties[key] = visible
				}
			}
		}
	}

	// Always pass through $virt_* bot classification properties
	// regardless of requested columns
	for _, key := range []string{"$virt_is_bot", "$virt_traffic_type", "$virt_traffic_category", "$virt_bot_name"} {
		if val, ok := event.Properties[key]; ok && !restrictions.RestrictsEventProperty(key) {
			properties[key] = val
		}
	}

	if pathCleaner != nil && !restrictions.RestrictsEventProperty("$pathname") {
		if pathname, ok := event.Properties["$pathname"].(string); ok {
			properties["$virt_cleaned_pathname"] = pathCleaner.Clean(pathname)
		}
	}

	return &ResponsePostHogEvent{
		Uuid:       event.Uuid,
		Timestamp:  event.Timestamp,
		DistinctId: event.DistinctId,
		PersonId:   uuidFromDistinctId(teamId, event.DistinctId),
		Event:      event.Event,
		Properties: properties,
	}
}

var personUUIDV5Namespace = uuid.Must(uuid.FromString("932979b4-65c3-4424-8467-0b66ec27bc22"))

func uuidFromDistinctId(teamId int, distinctId string) string {
	if teamId == 0 || distinctId == "" {
		return ""
	}

	input := fmt.Sprintf("%d:%s", teamId, distinctId)
	return uuid.NewV5(personUUIDV5Namespace, input).String()
}

func logUnsubscribe(sub Subscription) {
	if dropped := sub.DroppedEvents.Load(); dropped > 0 {
		log.Printf("Team %d dropped %d events", sub.TeamId, dropped)
	}
	metrics.SubTotal.Dec()
}

func removeSubscription(subID uint64, subs []Subscription) []Subscription {
	for i, sub := range subs {
		if subID == sub.SubID {
			logUnsubscribe(sub)
			return slices.Delete(subs, i, i+1)
		}
	}
	return subs
}

func (c *Filter) Run() {
	for {
		select {
		case newSub := <-c.SubChan:
			c.subs = append(c.subs, newSub)
			metrics.SubTotal.Inc()
		case unSub := <-c.UnSubChan:
			c.subs = removeSubscription(unSub.SubID, c.subs)
		case event := <-c.inboundChan:
			matching := make([]Subscription, 0, len(c.subs))
			for _, sub := range c.subs {
				if sub.Token != "" && event.Token != sub.Token {
					continue
				}
				matching = append(matching, sub)
			}
			deliverEvent(event, matching)
		}
	}
}

func matchesPropertyFilters(props map[string]interface{}, filters []CompiledPropertyFilter) bool {
	for i := range filters {
		if !filters[i].matches(props) {
			return false
		}
	}
	return true
}

func (f *CompiledPropertyFilter) hasValidRegex() bool {
	for _, re := range f.regexes {
		if re != nil {
			return true
		}
	}
	return false
}

func (f *CompiledPropertyFilter) matches(props map[string]interface{}) bool {
	raw, present := props[f.Key]

	switch f.Operator {
	case OpIsSet:
		return present
	case OpIsNotSet:
		return !present
	}

	if (f.Operator == OpRegex || f.Operator == OpNotRegex) && !f.hasValidRegex() {
		return false
	}

	if !present {
		switch f.Operator {
		case OpIsNot, OpNotIContains, OpNotRegex:
			return true
		default:
			return false
		}
	}

	actual := fmt.Sprint(raw)

	switch f.Operator {
	case OpExact:
		return slices.Contains(f.Values, actual)
	case OpIsNot:
		return !slices.Contains(f.Values, actual)
	case OpIContains:
		lower := strings.ToLower(actual)
		for _, v := range f.lowerValues {
			if strings.Contains(lower, v) {
				return true
			}
		}
		return false
	case OpNotIContains:
		lower := strings.ToLower(actual)
		for _, v := range f.lowerValues {
			if strings.Contains(lower, v) {
				return false
			}
		}
		return true
	case OpRegex:
		for _, re := range f.regexes {
			if re != nil && re.MatchString(actual) {
				return true
			}
		}
		return false
	case OpNotRegex:
		for _, re := range f.regexes {
			if re != nil && re.MatchString(actual) {
				return false
			}
		}
		return true
	case OpGreaterThan, OpGreaterEqual, OpLessThan, OpLessEqual:
		actualNum, err := strconv.ParseFloat(strings.TrimSpace(actual), 64)
		if err != nil {
			return false
		}
		for i, ok := range f.numericOK {
			if ok && compareNumeric(f.Operator, actualNum, f.numbers[i]) {
				return true
			}
		}
		return false
	default:
		return false
	}
}

func compareNumeric(operator string, actual, want float64) bool {
	switch operator {
	case OpGreaterThan:
		return actual > want
	case OpGreaterEqual:
		return actual >= want
	case OpLessThan:
		return actual < want
	case OpLessEqual:
		return actual <= want
	default:
		return false
	}
}

// Routes a single event to all matching subscriptions.
// Used by both Filter (in-memory path) and TokenRouter (Redis pub/sub path).
func deliverEvent(event PostHogEvent, subs []Subscription) {
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

		restrictions := sub.restrictions()
		if len(sub.PropertyFilters) > 0 {
			// The handler closes the stream when a re-check restricts a filtered key;
			// until it does, deliver nothing rather than leak matches.
			if RestrictedFilterKey(sub.PropertyFilters, restrictions) != "" {
				continue
			}
			if !matchesPropertyFilters(event.Properties, sub.PropertyFilters) {
				continue
			}
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
			responseEvent := convertToResponsePostHogEvent(event, sub.TeamId, sub.Columns, sub.PathCleaner, restrictions)

			select {
			case sub.EventChan <- *responseEvent:
			default:
				sub.DroppedEvents.Add(1)
				metrics.DroppedEvents.With(prometheus.Labels{"channel": "events"}).Inc()
			}
		}
	}
}
