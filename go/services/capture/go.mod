module github.com/PostHog/posthog/go/services/capture

go 1.24

require (
	github.com/PostHog/posthog/go/pkg/common v0.0.0
	github.com/go-chi/chi/v5 v5.2.1
)

replace github.com/PostHog/posthog/go/pkg/common => ../../pkg/common
