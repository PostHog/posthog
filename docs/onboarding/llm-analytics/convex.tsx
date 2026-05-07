import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getConvexSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, CalloutBox, Markdown, dedent, snippets } = ctx

    const NotableGenerationProperties = snippets?.NotableGenerationProperties

    return [
        {
            title: 'Install dependencies',
            badge: 'required',
            content: (
                <>
                    <Markdown>Install the PostHog AI package, the Vercel AI SDK, and the OpenTelemetry SDK.</Markdown>

                    <CodeBlock
                        language="bash"
                        code={dedent`
                            npm install @posthog/ai @ai-sdk/openai ai @opentelemetry/sdk-trace-base @opentelemetry/resources @opentelemetry/api
                        `}
                    />
                </>
            ),
        },
        {
            title: 'Set environment variables',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Set your PostHog project API key and host as Convex environment variables. You can find these in
                        your [project settings](https://app.posthog.com/settings/project).
                    </Markdown>

                    <CodeBlock
                        language="bash"
                        code={dedent`
                            npx convex env set POSTHOG_API_KEY "<ph_project_token>"
                            npx convex env set POSTHOG_HOST "<ph_client_api_host>"
                        `}
                    />

                    <Markdown>You also need your AI provider's API key (e.g. `OPENAI_API_KEY`):</Markdown>

                    <CodeBlock
                        language="bash"
                        code={dedent`
                            npx convex env set OPENAI_API_KEY "your_openai_api_key"
                        `}
                    />
                </>
            ),
        },
        {
            title: 'Capture LLM events with OpenTelemetry',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Create a Convex action that initializes a `BasicTracerProvider` with PostHog's trace exporter
                        and enables telemetry on your AI SDK calls. The provider is initialized at module scope so it
                        persists across warm V8 isolate invocations.
                    </Markdown>

                    <CodeBlock
                        language="typescript"
                        code={dedent`
                            import { trace } from '@opentelemetry/api'
                            import { BasicTracerProvider, SimpleSpanProcessor } from '@opentelemetry/sdk-trace-base'
                            import { resourceFromAttributes } from '@opentelemetry/resources'
                            import { generateText } from 'ai'
                            import { openai } from '@ai-sdk/openai'
                            import { PostHogTraceExporter } from '@posthog/ai/otel'
                            import { action } from './_generated/server'
                            import { v } from 'convex/values'

                            const provider = new BasicTracerProvider({
                              resource: resourceFromAttributes({
                                'service.name': 'my-convex-app',
                              }),
                              spanProcessors: [
                                new SimpleSpanProcessor(
                                  new PostHogTraceExporter({
                                    apiKey: process.env.POSTHOG_API_KEY!,
                                    host: process.env.POSTHOG_HOST,
                                  })
                                ),
                              ],
                            })
                            trace.setGlobalTracerProvider(provider)

                            export const generate = action({
                              args: {
                                prompt: v.string(),
                                distinctId: v.optional(v.string()),
                              },
                              handler: async (_ctx, args) => {
                                const distinctId = args.distinctId ?? 'anonymous'

                                const result = await generateText({
                                  model: openai('gpt-5-mini'),
                                  prompt: args.prompt,
                                  experimental_telemetry: {
                                    isEnabled: true,
                                    functionId: 'my-convex-action',
                                    metadata: {
                                      posthog_distinct_id: distinctId,
                                    },
                                  },
                                })

                                return { text: result.text, usage: result.usage }
                              },
                            })
                        `}
                    />

                    <CalloutBox type="fyi" icon="IconInfo" title="How this works">
                        <Markdown>
                            The `PostHogTraceExporter` sends OpenTelemetry `gen_ai.*` spans to PostHog's OTLP ingestion
                            endpoint. PostHog converts these into `$ai_generation` events automatically. The
                            `posthog_distinct_id` metadata field links events to a specific user.
                        </Markdown>
                    </CalloutBox>
                </>
            ),
        },
        {
            title: 'Using Convex Agent',
            badge: 'optional',
            content: (
                <>
                    <Markdown>
                        If you're using `@convex-dev/agent`, pass `experimental_telemetry` to the agent's `generateText`
                        call:
                    </Markdown>

                    <CodeBlock
                        language="typescript"
                        code={dedent`
                            import { trace } from '@opentelemetry/api'
                            import { BasicTracerProvider, SimpleSpanProcessor } from '@opentelemetry/sdk-trace-base'
                            import { resourceFromAttributes } from '@opentelemetry/resources'
                            import { Agent } from '@convex-dev/agent'
                            import { openai } from '@ai-sdk/openai'
                            import { PostHogTraceExporter } from '@posthog/ai/otel'
                            import { components } from './_generated/api'
                            import { action } from './_generated/server'
                            import { v } from 'convex/values'

                            const provider = new BasicTracerProvider({
                              resource: resourceFromAttributes({
                                'service.name': 'my-convex-app',
                              }),
                              spanProcessors: [
                                new SimpleSpanProcessor(
                                  new PostHogTraceExporter({
                                    apiKey: process.env.POSTHOG_API_KEY!,
                                    host: process.env.POSTHOG_HOST,
                                  })
                                ),
                              ],
                            })
                            trace.setGlobalTracerProvider(provider)

                            export const generate = action({
                              args: {
                                prompt: v.string(),
                                distinctId: v.optional(v.string()),
                              },
                              handler: async (ctx, args) => {
                                const distinctId = args.distinctId ?? 'anonymous'

                                const supportAgent = new Agent(components.agent, {
                                  name: 'support-agent',
                                  languageModel: openai('gpt-5-mini'),
                                  instructions: 'You are a helpful support agent.',
                                })

                                const { thread } = await supportAgent.createThread(ctx, {})

                                const result = await thread.generateText({
                                  prompt: args.prompt,
                                  experimental_telemetry: {
                                    isEnabled: true,
                                    functionId: 'convex-agent',
                                    metadata: {
                                      posthog_distinct_id: distinctId,
                                    },
                                  },
                                })

                                return { text: result.text, usage: result.totalUsage }
                              },
                            })
                        `}
                    />

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

export const ConvexInstallation = createInstallation(getConvexSteps)
