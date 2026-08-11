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
                        Install the PostHog AI package, the Vercel AI SDK, the OpenTelemetry SDK, and Zod for defining
                        tool schemas.
                    </Markdown>

                    <CodeBlock
                        language="bash"
                        code={dedent`
                            npm install @posthog/ai "ai@^6" "@ai-sdk/openai@^3" @opentelemetry/sdk-node @opentelemetry/resources zod
                        `}
                    />

                    <Blockquote>
                        <Markdown>
                            **AI SDK version:** this integration requires AI SDK v5 or v6. AI SDK v7 removed its
                            OpenTelemetry instrumentation, so it no longer emits the `ai.*` spans that
                            `PostHogSpanProcessor` reads, and `telemetry.metadata` is no longer accepted. Installing
                            `ai` without a version constraint gets you v7, which will not produce any events. Pin
                            `ai@^6` with the matching `@ai-sdk/openai@^3` until PostHog ships v7 support.
                        </Markdown>
                    </Blockquote>
                </>
            ),
        },
        {
            title: 'Set up the OpenTelemetry exporter',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Initialize the OpenTelemetry SDK with PostHog's `PostHogSpanProcessor`. This sends `gen_ai.*`
                        spans directly to PostHog's OTLP ingestion endpoint. PostHog converts these into
                        `$ai_generation` events automatically.
                    </Markdown>

                    <CodeBlock
                        language="typescript"
                        code={dedent`
                            import { NodeSDK } from '@opentelemetry/sdk-node'
                            import { resourceFromAttributes } from '@opentelemetry/resources'
                            import { PostHogSpanProcessor } from '@posthog/ai/otel'

                            const sdk = new NodeSDK({
                              resource: resourceFromAttributes({
                                'service.name': 'my-app',
                              }),
                              spanProcessors: [
                                new PostHogSpanProcessor({
                                  projectToken: '<ph_project_token>',
                                  host: '<ph_client_api_host>',
                                }),
                              ],
                            })
                            sdk.start()
                        `}
                    />
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
                            Pass \`experimental_telemetry\` to your Vercel AI SDK calls. The \`posthog_distinct_id\`
                            metadata field links events to a specific user in PostHog. Define \`tools\` the same way
                            you always would, with an \`execute\` function, as \`get_weather\` does below.
                        `}
                    </Markdown>

                    <CodeBlock
                        language="typescript"
                        code={dedent`
                            import { generateText, tool, stepCountIs } from 'ai'
                            import { openai } from '@ai-sdk/openai'
                            import { z } from 'zod'

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
                              experimental_telemetry: {
                                isEnabled: true,
                                functionId: 'my-ai-function',
                                metadata: {
                                  posthog_distinct_id: 'user_123', // optional
                                  posthog_environment: 'production', // custom property: sets "environment" on the event
                                  $ai_session_id: 'conversation-abc', // optional: groups calls into one session
                                },
                              },
                            })

                            console.log(result.text)
                        `}
                    />

                    <Blockquote>
                        <Markdown>
                            **Note:** If you want to capture LLM events anonymously, omit the `posthog_distinct_id`
                            metadata field. See our docs on [anonymous vs identified
                            events](https://posthog.com/docs/data/anonymous-vs-identified-events) to learn more.
                        </Markdown>
                    </Blockquote>

                    <Blockquote>
                        <Markdown>
                            **Custom properties:** Prefix any telemetry metadata field with `posthog_` to attach it to
                            the `$ai_generation` event as a custom property. PostHog strips the prefix, so
                            `posthog_environment` becomes an `environment` property you can filter and break down by.
                            PostHog does not capture other metadata fields.
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
