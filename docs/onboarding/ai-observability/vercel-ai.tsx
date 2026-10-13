import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getVercelAISteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, Blockquote, dedent, snippets } = ctx

    const NotableGenerationProperties = snippets?.NotableGenerationProperties

    return [
        {
            title: 'Install dependencies',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Use Node.js 22.22 or later. Install the PostHog AI package, the Vercel AI SDK, its OpenTelemetry
                        integration, the OpenTelemetry SDK, and Zod for defining tool schemas.
                    </Markdown>

                    <CodeBlock
                        language="bash"
                        code={dedent`
                            npm install @posthog/ai@^8.7.0 @ai-sdk/openai @ai-sdk/otel ai @opentelemetry/sdk-node @opentelemetry/resources zod
                        `}
                    />
                </>
            ),
        },
        {
            title: 'Set up the OpenTelemetry exporter',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Create `instrumentation.ts`. Initialize the OpenTelemetry SDK with PostHog's
                        `PostHogSpanProcessor`, then register the Vercel AI SDK integration. Both setup calls must
                        finish before the first AI SDK call. Their relative order does not matter because the
                        integration obtains a lazy OpenTelemetry tracer.
                    </Markdown>

                    <CodeBlock
                        language="typescript"
                        code={dedent`
                            import { OpenTelemetry } from '@ai-sdk/otel'
                            import { NodeSDK } from '@opentelemetry/sdk-node'
                            import { resourceFromAttributes } from '@opentelemetry/resources'
                            import { PostHogSpanProcessor } from '@posthog/ai/otel'
                            import { registerTelemetry } from 'ai'

                            export const posthogSpanProcessor = new PostHogSpanProcessor({
                              projectToken: '<ph_project_token>',
                              host: '<ph_client_api_host>',
                            })

                            const sdk = new NodeSDK({
                              resource: resourceFromAttributes({
                                'service.name': 'my-app',
                              }),
                              spanProcessors: [posthogSpanProcessor],
                            })

                            sdk.start()

                            registerTelemetry(
                              new OpenTelemetry({
                                enrichSpan: ({ runtimeContext }) => ({
                                  environment:
                                    typeof runtimeContext?.properties === 'object' &&
                                    runtimeContext.properties !== null &&
                                    'environment' in runtimeContext.properties &&
                                    typeof runtimeContext.properties.environment === 'string'
                                      ? runtimeContext.properties.environment
                                      : undefined,
                                  'posthog.distinct_id':
                                    typeof runtimeContext?.distinctId === 'string'
                                      ? runtimeContext.distinctId
                                      : undefined,
                                  '$ai_session_id':
                                    typeof runtimeContext?.sessionId === 'string'
                                      ? runtimeContext.sessionId
                                      : undefined,
                                  '$ai_trace_name':
                                    typeof runtimeContext?.traceName === 'string'
                                      ? runtimeContext.traceName
                                      : undefined,
                                  '$groups':
                                    typeof runtimeContext?.groups === 'object' &&
                                    runtimeContext.groups !== null &&
                                    !Array.isArray(runtimeContext.groups)
                                      ? JSON.stringify(runtimeContext.groups)
                                      : undefined,
                                }),
                              })
                            )
                        `}
                    />

                    <Blockquote>
                        <Markdown>
                            **Request-scoped runtimes:** Keep the processor reference and await
                            `posthogSpanProcessor.forceFlush()` before the request lifecycle ends, or attach the promise
                            to a supported lifecycle hook such as `waitUntil`. Long-running services can flush during
                            graceful shutdown instead.
                        </Markdown>
                    </Blockquote>

                    <Blockquote>
                        <Markdown>
                            **Vercel AI SDK versions:** This OpenTelemetry integration is the supported path for Vercel
                            AI SDK v7. The legacy PostHog `withTracing` wrapper supports the v5 and v6 provider
                            interfaces and rejects v7 models.
                        </Markdown>
                    </Blockquote>
                </>
            ),
        },
        {
            title: 'Call Vercel AI with telemetry enabled',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Pass request data through \`runtimeContext\`, then select the fields that the telemetry
                            integration can receive with \`telemetry.includeRuntimeContext\`. Define \`tools\` the same
                            way you normally would, with an \`execute\` function, as \`get_weather\` does below.
                        `}
                    </Markdown>

                    <CodeBlock
                        language="typescript"
                        code={dedent`
                            import { generateText, tool, stepCountIs } from 'ai'
                            import { openai } from '@ai-sdk/openai'
                            import { z } from 'zod'
                            import { posthogSpanProcessor } from './instrumentation'

                            async function runWeatherAgent(): Promise<string> {
                              const result = await generateText({
                                model: openai('gpt-5-mini'),
                                prompt: "What's the weather in Paris?",
                                tools: {
                                  get_weather: tool({
                                    description: 'Get the weather for a city',
                                    inputSchema: z.object({ city: z.string() }),
                                    execute: async ({ city }) => \`It's always sunny in \${city}!\`,
                                  }),
                                },
                                stopWhen: stepCountIs(5), // let the model see the tool result and respond
                                runtimeContext: {
                                  distinctId: 'user_123',
                                  sessionId: 'conversation-abc',
                                  traceName: 'weather-agent',
                                  groups: {
                                    company: 'company_123',
                                  },
                                  properties: {
                                    environment: 'production',
                                  },
                                },
                                telemetry: {
                                  functionId: 'my-ai-function',
                                  includeRuntimeContext: {
                                    distinctId: true,
                                    sessionId: true,
                                    traceName: true,
                                    groups: true,
                                    properties: true,
                                  },
                                },
                              })

                              return result.text
                            }

                            try {
                              console.log(await runWeatherAgent())
                            } finally {
                              // Spans are still queued in the batch processor when this script exits,
                              // so without this flush they never reach PostHog.
                              await posthogSpanProcessor.forceFlush()
                            }
                        `}
                    />

                    <Blockquote>
                        <Markdown>
                            **Identity:** Provide `distinctId` for stable user attribution. Omitting it does not make
                            capture anonymous. PostHog assigns fallback IDs when no distinct ID is present.
                        </Markdown>
                    </Blockquote>

                    <Blockquote>
                        <Markdown>
                            **Groups and custom properties:** PostHog ingestion converts the JSON-string `$groups`
                            attribute into native group associations. Other scalar attributes returned by `enrichSpan`,
                            such as `environment`, remain filterable custom properties.
                        </Markdown>
                    </Blockquote>

                    <Blockquote>
                        <Markdown>
                            **Trace and session names:** `$ai_session_id` groups calls in AI observability. Trace names
                            are not configurable on the v7 OpenTelemetry path yet. PostHog derives the displayed trace
                            name from the OpenTelemetry span name, which takes precedence over `$ai_trace_name`.
                            `functionId` is emitted as `gen_ai.agent.name` and does not set the trace name either.
                        </Markdown>
                    </Blockquote>

                    <Blockquote>
                        <Markdown>
                            **Runtime context support:** Current `@ai-sdk/otel` releases pass `runtimeContext` to
                            `enrichSpan` for `generateText` and `streamText`. Object generation, embeddings, and
                            reranking do not pass runtime context yet.
                        </Markdown>
                    </Blockquote>

                    <Blockquote>
                        <Markdown>
                            **Privacy:** Vercel AI SDK v7 records prompts and outputs by default. Set `recordInputs:
                            false` or `recordOutputs: false` in `telemetry` to disable either field. The OpenTelemetry
                            path does not have a separate PostHog privacy switch for text content, so these flags are
                            the control for prompt and output recording.
                        </Markdown>
                    </Blockquote>

                    <Markdown>
                        {dedent`
                            You can expect captured \`$ai_generation\` events to have the following properties:
                        `}
                    </Markdown>

                    {NotableGenerationProperties && <NotableGenerationProperties />}
                </>
            ),
        },
    ]
}

export const VercelAIInstallation = createInstallation(getVercelAISteps)
