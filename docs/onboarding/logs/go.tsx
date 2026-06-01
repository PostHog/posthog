import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getGoSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    return [
        {
            title: 'Install dependencies',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        PostHog logs uses the standard OpenTelemetry SDK. No PostHog-specific packages required.
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'go',
                                code: dedent`
                                    go get go.opentelemetry.io/otel
                                    go get go.opentelemetry.io/otel/sdk
                                    go get go.opentelemetry.io/otel/log
                                    go get go.opentelemetry.io/otel/exporters/otlp/otlplog/otlploghttp
                                    go get go.opentelemetry.io/otel/sdk/log
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Configure the OTLP log exporter',
            badge: 'required',
            content: (
                <>
                    <Markdown>Configure the OpenTelemetry log exporter to send logs to PostHog:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'go',
                                file: 'instrumentation.go',
                                code: dedent`
                                    package main

                                    import (
                                        "context"

                                        "go.opentelemetry.io/otel/exporters/otlp/otlplog/otlploghttp"
                                        "go.opentelemetry.io/otel/log/global"
                                        sdklog "go.opentelemetry.io/otel/sdk/log"
                                        "go.opentelemetry.io/otel/sdk/resource"
                                        semconv "go.opentelemetry.io/otel/semconv/v1.26.0"
                                    )

                                    func setupLogging(ctx context.Context) (*sdklog.LoggerProvider, error) {
                                        exporter, err := otlploghttp.New(ctx,
                                            otlploghttp.WithEndpointURL("<ph_client_api_host>/otlp/v1/logs"),
                                            otlploghttp.WithHeaders(map[string]string{
                                                "Authorization": "Bearer <ph_project_token>",
                                            }),
                                        )
                                        if err != nil {
                                            return nil, err
                                        }

                                        res := resource.NewWithAttributes(
                                            semconv.SchemaURL,
                                            semconv.ServiceName("my-app"),
                                        )

                                        provider := sdklog.NewLoggerProvider(
                                            sdklog.WithProcessor(sdklog.NewBatchProcessor(exporter)),
                                            sdklog.WithResource(res),
                                        )

                                        global.SetLoggerProvider(provider)
                                        return provider, nil
                                    }
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Send a log',
            badge: 'required',
            content: (
                <>
                    <Markdown>Use the OpenTelemetry logger to emit logs from your application:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'go',
                                file: 'main.go',
                                code: dedent`
                                    package main

                                    import (
                                        "context"
                                        "log"

                                        "go.opentelemetry.io/otel/log/global"
                                        semconv "go.opentelemetry.io/otel/semconv/v1.26.0"
                                        otellog "go.opentelemetry.io/otel/log"
                                    )

                                    func main() {
                                        ctx := context.Background()

                                        provider, err := setupLogging(ctx)
                                        if err != nil {
                                            log.Fatal(err)
                                        }
                                        defer provider.Shutdown(ctx)

                                        logger := global.Logger("my-app")

                                        var record otellog.Record
                                        record.SetSeverity(otellog.SeverityInfo)
                                        record.SetBody(otellog.StringValue("Application started"))
                                        record.AddAttributes(
                                            otellog.Int64("server.port", 8080),
                                        )
                                        logger.Emit(ctx, record)
                                    }
                                `,
                            },
                        ]}
                    />
                    <Markdown>
                        Logs appear in PostHog within a few seconds. Use the [Logs page](/logs) to search and filter by
                        service name, severity, or any attribute you attach.
                    </Markdown>
                </>
            ),
        },
    ]
}

export const GoInstallation = createInstallation(getGoSteps)
