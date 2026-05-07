import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getNodeJSSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    return [
        {
            title: 'Install dependencies',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        PostHog logs uses the standard OpenTelemetry SDK. No PostHog-specific packages required. Install
                        the OTel SDK and the logs signal package:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'npm',
                                code: dedent`
                                    npm install @opentelemetry/sdk-node @opentelemetry/sdk-logs @opentelemetry/exporter-logs-otlp-http @opentelemetry/resources
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'yarn',
                                code: dedent`
                                    yarn add @opentelemetry/sdk-node @opentelemetry/sdk-logs @opentelemetry/exporter-logs-otlp-http @opentelemetry/resources
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'pnpm',
                                code: dedent`
                                    pnpm add @opentelemetry/sdk-node @opentelemetry/sdk-logs @opentelemetry/exporter-logs-otlp-http @opentelemetry/resources
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'bun',
                                code: dedent`
                                    bun add @opentelemetry/sdk-node @opentelemetry/sdk-logs @opentelemetry/exporter-logs-otlp-http @opentelemetry/resources
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
                    <Markdown>
                        {dedent`
                            Create a logger setup file that configures the OpenTelemetry log exporter to send logs to
                            PostHog. Call this before your application starts.
                        `}
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'typescript',
                                file: 'logger.ts',
                                code: dedent`
                                    import { OTLPLogExporter } from '@opentelemetry/exporter-logs-otlp-http'
                                    import { resourceFromAttributes } from '@opentelemetry/resources'
                                    import { LoggerProvider, SimpleLogRecordProcessor } from '@opentelemetry/sdk-logs'

                                    const exporter = new OTLPLogExporter({
                                      url: '<ph_client_api_host>/otlp/v1/logs',
                                      headers: {
                                        Authorization: 'Bearer <ph_project_token>',
                                      },
                                    })

                                    const loggerProvider = new LoggerProvider({
                                      resource: resourceFromAttributes({
                                        'service.name': 'my-app',
                                      }),
                                    })

                                    loggerProvider.addLogRecordProcessor(new SimpleLogRecordProcessor(exporter))

                                    export const logger = loggerProvider.getLogger('my-app')
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
                    <Markdown>Use the logger to emit logs from your application:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'typescript',
                                file: 'app.ts',
                                code: dedent`
                                    import { SeverityNumber } from '@opentelemetry/api-logs'
                                    import { logger } from './logger'

                                    logger.emit({
                                      severityNumber: SeverityNumber.INFO,
                                      severityText: 'INFO',
                                      body: 'Server started',
                                      attributes: {
                                        'server.port': 3000,
                                        'server.env': 'production',
                                      },
                                    })
                                `,
                            },
                        ]}
                    />
                    <Markdown>
                        {dedent`
                            Logs appear in PostHog within a few seconds. Use the [Logs page](https://app.posthog.com/logs) to search and filter
                            by service name, severity, or any attribute you attach.
                        `}
                    </Markdown>
                </>
            ),
        },
    ]
}

export const NodeJSInstallation = createInstallation(getNodeJSSteps)
