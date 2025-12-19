package installer

import (
	"bytes"
	"encoding/json"
	"net/http"
	"time"
)

const (
	posthogAPIKey  = "sTMFPsFhdP1Ssg"
	posthogAPIURL  = "https://us.i.posthog.com/batch/"
	requestTimeout = 5 * time.Second
)

type posthogEvent struct {
	APIKey     string            `json:"api_key"`
	DistinctID string            `json:"distinct_id"`
	Properties map[string]string `json:"properties"`
	Type       string            `json:"type"`
	Event      string            `json:"event"`
}

func SendInstallStartEvent(domain string) {
	sendEvent(domain, "magic_curl_install_start")
}

func SendInstallCompleteEvent(domain string) {
	sendEvent(domain, "magic_curl_install_complete")
}

func sendEvent(domain, eventName string) {
	event := posthogEvent{
		APIKey:     posthogAPIKey,
		DistinctID: domain,
		Properties: map[string]string{"domain": domain},
		Type:       "capture",
		Event:      eventName,
	}

	body, err := json.Marshal(event)
	if err != nil {
		return // Silently fail - telemetry should never block installation
	}

	client := &http.Client{Timeout: requestTimeout}
	req, err := http.NewRequest("POST", posthogAPIURL, bytes.NewBuffer(body))
	if err != nil {
		return
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := client.Do(req)
	if err != nil {
		return
	}
	resp.Body.Close()
}

