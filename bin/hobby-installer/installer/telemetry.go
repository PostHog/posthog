package installer

import (
	"github.com/posthog/posthog-go"
)

const posthogAPIKey = "sTMFPsFhdP1Ssg"
const endpoint = "https://us.i.posthog.com"

var client posthog.Client

// Go's `init` function is called automatically when the package is imported.
func init() {
	var err error
	client, err = posthog.NewWithConfig(posthogAPIKey, posthog.Config{
		Endpoint: endpoint,
	})

	// Just keep going even if we get an error,
	// not having telemtry isn't a blocker for the installer
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
		client.Close()
	}
}
