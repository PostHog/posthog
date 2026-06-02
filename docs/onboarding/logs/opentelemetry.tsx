import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getOpenTelemetrySteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    return [
        {
            title: 'Send logs via OTLP',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            PostHog accepts logs from any OpenTelemetry-compatible client via OTLP over HTTP.
                            Point your exporter at PostHog's OTLP endpoint and authenticate with your project token.

                            PostHog does not require any PostHog-specific SDK or package — use standard
                            OpenTelemetry libraries in any language.
                        `}
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'Environment variables',
                                code: dedent`
                                    OTEL_EXPORTER_OTLP_LOGS_ENDPOINT="<ph_client_api_host>/otlp/v1/logs"
                                    OTEL_EXPORTER_OTLP_LOGS_HEADERS="Authorization=Bearer <ph_project_token>"
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
                                        logs_endpoint: "<ph_client_api_host>/otlp/v1/logs"
                                        headers:
                                          Authorization: "Bearer <ph_project_token>"

                                    service:
                                      pipelines:
                                        logs:
                                          receivers: [otlp]
                                          processors: [batch]
                                          exporters: [otlphttp/posthog]
                                `,
                            },
                        ]}
                    />
                    <Markdown>
                        {dedent`
                            The endpoint accepts OTLP over HTTP in both \`application/x-protobuf\` and \`application/json\`
                            formats. gRPC is not supported, use the HTTP transport protocol instead.

                            Logs appear in PostHog within a few seconds. Use the [Logs page](https://app.posthog.com/logs) to search and filter
                            by service name, severity, or any attribute you attach.
                        `}
                    </Markdown>
                </>
            ),
        },
    ]
}

export const OpenTelemetryInstallation = createInstallation(getOpenTelemetrySteps)
