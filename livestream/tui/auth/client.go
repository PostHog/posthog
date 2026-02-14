package auth

import "strings"

func DeriveStreamHost(appHost string) string {
	appHost = strings.TrimRight(appHost, "/")

	switch appHost {
	case "https://us.posthog.com", "https://app.posthog.com":
		return "https://live.us.posthog.com"
	case "https://eu.posthog.com":
		return "https://live.eu.posthog.com"
	case "https://app.dev.posthog.dev":
		return "https://live.dev.posthog.dev"
	default:
		return "http://localhost:8010" // Local development stream host
	}
}
