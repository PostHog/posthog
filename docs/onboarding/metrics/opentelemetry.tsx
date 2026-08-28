import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getOpenTelemetrySteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    return [
        {
            title: 'Scrape a Prometheus endpoint',
            badge: 'recommended',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            If your services already expose a Prometheus \`/metrics\` endpoint, run the PostHog
                            metrics agent. It scrapes those endpoints and forwards them to PostHog, so your
                            application code does not change.
                        `}
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'Docker',
                                code: dedent`
                                    docker run -d --name posthog-metrics-agent \\
                                      -e POSTHOG_API_KEY=<ph_project_token> \\
                                      -e POSTHOG_HOST=<ph_client_api_host> \\
                                      -e SCRAPE_TARGETS=your-app:9090,your-worker:9091 \\
                                      posthog/metrics-agent:latest
                                `,
                            },
                        ]}
                    />
                    <Markdown>
                        {dedent`
                            \`SCRAPE_TARGETS\` is a comma-separated list of \`host:port\` targets to scrape.

                            On Kubernetes, the Helm chart in \`products/metrics/agent/chart\` runs the same image.
                            Set \`shards\` to spread targets across a fleet, and \`persistence.enabled=true\` to keep
                            the export queue across restarts.

                            Counters and histograms scraped with OpenMetrics exemplars become clickable trace
                            links. Your Prometheus client has to attach the exemplars, the agent only preserves them.
                        `}
                    </Markdown>
                </>
            ),
        },
        {
            title: 'Send metrics over OTLP',
            badge: 'optional',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            If you instrument your application directly, PostHog accepts metrics from any
                            OpenTelemetry client over OTLP HTTP. There is no PostHog-specific package to install,
                            use the standard OpenTelemetry libraries for your language.
                        `}
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'Environment variables',
                                code: dedent`
                                    OTEL_EXPORTER_OTLP_METRICS_ENDPOINT="<ph_client_api_host>/i/v1/metrics"
                                    OTEL_EXPORTER_OTLP_METRICS_HEADERS="Authorization=Bearer <ph_project_token>"
                                    OTEL_SERVICE_NAME="my-app"
                                `,
                            },
                            {
                                language: 'yaml',
                                file: 'OTel Collector',
                                code: dedent`
                                    receivers:
                                      otlp:
                                        protocols:
                                          http:
                                            endpoint: 0.0.0.0:4318

                                    processors:
                                      batch:

                                    exporters:
                                      otlphttp/posthog:
                                        metrics_endpoint: "<ph_client_api_host>/i/v1/metrics"
                                        headers:
                                          Authorization: "Bearer <ph_project_token>"

                                    service:
                                      pipelines:
                                        metrics:
                                          receivers: [otlp]
                                          processors: [batch]
                                          exporters: [otlphttp/posthog]
                                `,
                            },
                        ]}
                    />
                    <Markdown>
                        {dedent`
                            The endpoint accepts OTLP over HTTP as \`application/x-protobuf\` or
                            \`application/json\`. gRPC is not supported, use the HTTP transport instead.

                            Gauges, sums, histograms, exponential histograms, and summaries are all accepted.
                            Keep label cardinality low: values like user IDs or request IDs create a new series
                            each time and get rate limited.
                        `}
                    </Markdown>
                </>
            ),
        },
    ]
}

export const OpenTelemetryInstallation = createInstallation(getOpenTelemetrySteps)
