import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getNextJSSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
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
                                    npm install @opentelemetry/sdk-logs @opentelemetry/exporter-logs-otlp-http @opentelemetry/resources
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'yarn',
                                code: dedent`
                                    yarn add @opentelemetry/sdk-logs @opentelemetry/exporter-logs-otlp-http @opentelemetry/resources
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'pnpm',
                                code: dedent`
                                    pnpm add @opentelemetry/sdk-logs @opentelemetry/exporter-logs-otlp-http @opentelemetry/resources
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'bun',
                                code: dedent`
                                    bun add @opentelemetry/sdk-logs @opentelemetry/exporter-logs-otlp-http @opentelemetry/resources
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Create an instrumentation file',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Next.js loads \`instrumentation.ts\` (or \`instrumentation.js\`) at startup.
                            Add the log exporter configuration there:
                        `}
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'typescript',
                                file: 'instrumentation.ts',
                                code: dedent`
                                    import { OTLPLogExporter } from '@opentelemetry/exporter-logs-otlp-http'
                                    import { resourceFromAttributes } from '@opentelemetry/resources'
                                    import { LoggerProvider, SimpleLogRecordProcessor } from '@opentelemetry/sdk-logs'

                                    export function register() {
                                      if (process.env.NEXT_RUNTIME === 'nodejs') {
                                        const exporter = new OTLPLogExporter({
                                          url: '<ph_client_api_host>/otlp/v1/logs',
                                          headers: {
                                            Authorization: 'Bearer <ph_project_token>',
                                          },
                                        })

                                        const loggerProvider = new LoggerProvider({
                                          resource: resourceFromAttributes({
                                            'service.name': 'my-nextjs-app',
                                          }),
                                        })

                                        loggerProvider.addLogRecordProcessor(new SimpleLogRecordProcessor(exporter))

                                        // make the logger available globally
                                        ;(globalThis as any).__posthogLogger = loggerProvider.getLogger('my-nextjs-app')
                                      }
                                    }
                                `,
                            },
                        ]}
                    />
                    <Markdown>
                        {dedent`
                            Enable the instrumentation hook in \`next.config.ts\`:
                        `}
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'typescript',
                                file: 'next.config.ts',
                                code: dedent`
                                    import type { NextConfig } from 'next'

                                    const nextConfig: NextConfig = {
                                      experimental: {
                                        instrumentationHook: true,
                                      },
                                    }

                                    export default nextConfig
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
                    <Markdown>Use the global logger in your API routes or server components:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'typescript',
                                file: 'app/api/route.ts',
                                code: dedent`
                                    import { SeverityNumber } from '@opentelemetry/api-logs'

                                    export async function GET() {
                                      const logger = (globalThis as any).__posthogLogger
                                      logger?.emit({
                                        severityNumber: SeverityNumber.INFO,
                                        severityText: 'INFO',
                                        body: 'API route called',
                                        attributes: { route: '/api' },
                                      })
                                      return Response.json({ ok: true })
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

export const NextJSInstallation = createInstallation(getNextJSSteps)
