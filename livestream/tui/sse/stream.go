package sse

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"math"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/posthog/posthog/livestream/tui/debug"
)

const maxBuffer = 4096

type StreamStateMsg struct {
	GeoOnly      bool
	Connected    bool
	Reconnecting bool
	Attempt      int
}

type Stream struct {
	client  *Client
	geoOnly bool
	ctx     context.Context
	cancel  context.CancelFunc
	label   string

	mu      sync.Mutex
	events  []EventMsg
	geos    []GeoEventMsg
	state   *StreamStateMsg
	dropped int64
}

func NewStream(client *Client, geoOnly bool, ctx context.Context) *Stream {
	streamCtx, cancel := context.WithCancel(ctx)
	label := "events"
	if geoOnly {
		label = "geo"
	}
	s := &Stream{
		client:  client,
		geoOnly: geoOnly,
		ctx:     streamCtx,
		cancel:  cancel,
		label:   label,
	}
	if geoOnly {
		s.geos = make([]GeoEventMsg, 0, 128)
	} else {
		s.events = make([]EventMsg, 0, 128)
	}
	go s.run()
	return s
}

func (s *Stream) Stop() {
	debug.Log(s.label, "stream stopped")
	s.cancel()
}

// FlushEvents swaps the internal events buffer with reuse and returns the
// accumulated events. After initial warmup this is zero-allocation: the caller
// passes back the slice it received last time (already processed) and gets the
// new batch in return.
func (s *Stream) FlushEvents(reuse []EventMsg) ([]EventMsg, *StreamStateMsg) {
	s.mu.Lock()
	out := s.events
	s.events = reuse[:0]
	state := s.state
	s.state = nil
	s.mu.Unlock()
	return out, state
}

// FlushGeo is the geo-stream equivalent of FlushEvents.
func (s *Stream) FlushGeo(reuse []GeoEventMsg) ([]GeoEventMsg, *StreamStateMsg) {
	s.mu.Lock()
	out := s.geos
	s.geos = reuse[:0]
	state := s.state
	s.state = nil
	s.mu.Unlock()
	return out, state
}

func (s *Stream) pushEventMsg(e EventMsg) {
	s.mu.Lock()
	if len(s.events) < maxBuffer {
		s.events = append(s.events, e)
	} else {
		s.dropped++
		if s.dropped%1000 == 1 {
			debug.Log(s.label, "buffer full (%d), dropped %d total", maxBuffer, s.dropped)
		}
	}
	s.mu.Unlock()
}

func (s *Stream) pushGeoMsg(g GeoEventMsg) {
	s.mu.Lock()
	if len(s.geos) < maxBuffer {
		s.geos = append(s.geos, g)
	} else {
		s.dropped++
		if s.dropped%1000 == 1 {
			debug.Log(s.label, "buffer full (%d), dropped %d total", maxBuffer, s.dropped)
		}
	}
	s.mu.Unlock()
}

func (s *Stream) pushState(msg StreamStateMsg) {
	s.mu.Lock()
	s.state = &msg
	s.mu.Unlock()
}

func (s *Stream) stats() (bufLen int, dropped int64) {
	s.mu.Lock()
	if s.geoOnly {
		bufLen = len(s.geos)
	} else {
		bufLen = len(s.events)
	}
	dropped = s.dropped
	s.mu.Unlock()
	return
}

func (s *Stream) run() {
	attempt := 0
	for {
		if s.ctx.Err() != nil {
			return
		}

		if attempt > 0 {
			delay := time.Duration(math.Min(
				float64(time.Second)*math.Pow(2, float64(attempt-1)),
				float64(30*time.Second),
			))
			debug.Log(s.label, "reconnecting (attempt %d, delay %s)", attempt, delay)
			s.pushState(StreamStateMsg{GeoOnly: s.geoOnly, Reconnecting: true, Attempt: attempt})

			select {
			case <-time.After(delay):
			case <-s.ctx.Done():
				return
			}
		}

		err := s.connectAndStream()
		if s.ctx.Err() != nil {
			return
		}

		if err != nil {
			debug.Log(s.label, "connection error: %v", err)
			s.pushState(StreamStateMsg{GeoOnly: s.geoOnly, Connected: false})
			attempt++
			continue
		}

		debug.Log(s.label, "stream ended normally, reconnecting immediately")
		attempt = 0
	}
}

func (s *Stream) connectAndStream() error {
	params := []string{}
	if s.client.eventType != "" {
		params = append(params, "eventType="+url.QueryEscape(s.client.eventType))
	}
	if s.client.distinctID != "" {
		params = append(params, "distinctId="+url.QueryEscape(s.client.distinctID))
	}
	if s.geoOnly {
		params = append(params, "geo=true")
	}

	endpoint := s.client.Host + "/events"
	if len(params) > 0 {
		endpoint += "?" + strings.Join(params, "&")
	}

	debug.Log(s.label, "connecting to %s", endpoint)

	req, err := http.NewRequestWithContext(s.ctx, "GET", endpoint, nil)
	if err != nil {
		return fmt.Errorf("request create: %w", err)
	}
	req.Header.Set("Authorization", "Bearer "+s.client.Token)
	req.Header.Set("Accept", "text/event-stream")

	resp, err := s.client.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("request failed: %w", err)
	}
	defer resp.Body.Close() //nolint:errcheck

	if resp.StatusCode == http.StatusUnauthorized {
		return fmt.Errorf("unauthorized (401)")
	}
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("unexpected status: %d", resp.StatusCode)
	}

	debug.Log(s.label, "connected (status 200)")

	s.pushState(StreamStateMsg{GeoOnly: s.geoOnly, Connected: true})

	scanner := bufio.NewScanner(resp.Body)
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024) // 1MB max line

	dataLines := make([]string, 0, 4)
	eventCount := 0
	lastCountLog := time.Now()

	for scanner.Scan() {
		if s.ctx.Err() != nil {
			return nil
		}

		line := scanner.Text()

		if strings.HasPrefix(line, "data: ") {
			dataLines = append(dataLines, strings.TrimPrefix(line, "data: "))
			continue
		}

		if strings.HasPrefix(line, "id:") || strings.HasPrefix(line, ":") {
			continue
		}

		if line == "" && len(dataLines) > 0 {
			var data string
			if len(dataLines) == 1 {
				data = dataLines[0]
			} else {
				data = strings.Join(dataLines, "\n")
			}
			dataLines = dataLines[:0]

			if s.geoOnly {
				var geo GeoEventMsg
				if err := json.Unmarshal([]byte(data), &geo); err != nil {
					debug.Log(s.label, "json parse error: %v (len=%d)", err, len(data))
					continue
				}
				geo.ReceivedAt = time.Now()
				s.pushGeoMsg(geo)
			} else {
				var event EventMsg
				if err := json.Unmarshal([]byte(data), &event); err != nil {
					debug.Log(s.label, "json parse error: %v (len=%d)", err, len(data))
					continue
				}
				event.ReceivedAt = time.Now()
				s.pushEventMsg(event)
			}

			eventCount++
			if time.Since(lastCountLog) >= 10*time.Second {
				bufLen, dropped := s.stats()
				debug.Log(s.label, "received %d events in last 10s (buf: %d, dropped: %d)", eventCount, bufLen, dropped)
				eventCount = 0
				lastCountLog = time.Now()
			}
		}
	}

	if err := scanner.Err(); err != nil {
		return fmt.Errorf("scanner: %w", err)
	}
	return nil
}
