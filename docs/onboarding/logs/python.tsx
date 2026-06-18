import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getPythonSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
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
                                file: 'pip',
                                code: dedent`
                                    pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http
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
                                language: 'python',
                                file: 'instrumentation.py',
                                code: dedent`
                                    from opentelemetry._logs import set_logger_provider
                                    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
                                    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
                                    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
                                    from opentelemetry.sdk.resources import Resource
                                    import logging

                                    resource = Resource(attributes={"service.name": "my-app"})

                                    logger_provider = LoggerProvider(resource=resource)
                                    set_logger_provider(logger_provider)

                                    exporter = OTLPLogExporter(
                                        endpoint="<ph_client_api_host>/otlp/v1/logs",
                                        headers={"Authorization": "Bearer <ph_project_token>"},
                                    )
                                    logger_provider.add_log_record_processor(BatchLogRecordProcessor(exporter))

                                    # Bridge standard library logging to OTel
                                    handler = LoggingHandler(logger_provider=logger_provider)
                                    logging.getLogger().addHandler(handler)
                                    logging.getLogger().setLevel(logging.INFO)
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
                    <Markdown>
                        Once configured, use the standard Python `logging` module. Logs are forwarded automatically:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'python',
                                file: 'app.py',
                                code: dedent`
                                    import logging
                                    from instrumentation import *  # noqa: F401 – sets up the handler

                                    logger = logging.getLogger(__name__)

                                    logger.info("Request processed", extra={"request_id": "req_abc", "duration_ms": 42})
                                    logger.warning("High memory usage", extra={"usage_mb": 1024})
                                    logger.error("Database connection failed", extra={"host": "db.example.com"})
                                `,
                            },
                        ]}
                    />
                    <Markdown>
                        Logs appear in PostHog within a few seconds. Use the [Logs page](https://app.posthog.com/logs)
                        to search and filter by service name, severity, or any attribute you attach.
                    </Markdown>
                </>
            ),
        },
    ]
}

export const PythonInstallation = createInstallation(getPythonSteps)
