package core

import (
	"github.com/posthog/posthog-go"
)

const posthogAPIKey = "sTMFPsFhdP1Ssg"
const endpoint = "https://us.i.posthog.com"

var client posthog.Client

func init() {
	var err error
	client, err = posthog.NewWithConfig(posthogAPIKey, posthog.Config{
		Endpoint: endpoint,
	})
	if err != nil {
		client = nil
	}
}

func SendInstallStartEvent(domain string) {
	sendEvent(domain, "magic_curl_install_start")
}

func SendInstallCompleteEvent(domain string) {
	sendEvent(domain, "magic_curl_install_complete")
}

func sendEvent(domain, eventName string) {
	if client == nil {
		return
	}

	_ = client.Enqueue(posthog.Capture{
		DistinctId: domain,
		Event:      eventName,
		Properties: posthog.NewProperties().Set("domain", domain),
	})
}

func CloseTelemetry() {
	if client != nil {
		_ = client.Close()
	}
}
