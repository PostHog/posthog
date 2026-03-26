import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getVercelAISteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, CalloutBox, Markdown, Blockquote, dedent, snippets } = ctx

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
                            npm install @posthog/ai @ai-sdk/openai ai @opentelemetry/sdk-node @opentelemetry/resources
                        `}
                    />

                    <CalloutBox type="fyi" icon="IconInfo" title="No proxy">
                        <Markdown>
                            These SDKs **do not** proxy your calls. They only send analytics data to PostHog in the
                            background.
                        </Markdown>
                    </CalloutBox>
                </>
            ),
        },
        {
            title: 'Set up the OpenTelemetry exporter',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Initialize the OpenTelemetry SDK with PostHog's `PostHogTraceExporter`. This sends `gen_ai.*`
                        spans directly to PostHog's OTLP ingestion endpoint. PostHog converts these into
                        `$ai_generation` events automatically.
                    </Markdown>

                    <CodeBlock
                        language="typescript"
                        code={dedent`
                            import { NodeSDK } from '@opentelemetry/sdk-node'
                            import { resourceFromAttributes } from '@opentelemetry/resources'
                            import { PostHogTraceExporter } from '@posthog/ai/otel'

                            const sdk = new NodeSDK({
                              resource: resourceFromAttributes({
                                'service.name': 'my-ai-app',
                              }),
                              traceExporter: new PostHogTraceExporter({
                                apiKey: '<ph_project_token>',
                                host: '<ph_client_api_host>',
                              }),
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
                        Pass `experimental_telemetry` to your Vercel AI SDK calls. The `posthog_distinct_id` metadata
                        field links events to a specific user in PostHog.
                    </Markdown>

                    <CodeBlock
                        language="typescript"
                        code={dedent`
                            import { generateText } from 'ai'
                            import { openai } from '@ai-sdk/openai'

                            const result = await generateText({
                              model: openai('gpt-5-mini'),
                              prompt: 'Tell me a fun fact about hedgehogs.',
                              experimental_telemetry: {
                                isEnabled: true,
                                functionId: 'my-ai-function',
                                metadata: {
                                  posthog_distinct_id: 'user_123', // optional
                                },
                              },
                            })

                            console.log(result.text)

                            await sdk.shutdown()
                        `}
                    />

                    <Blockquote>
                        <Markdown>
                            **Note:** If you want to capture LLM events anonymously, omit the `posthog_distinct_id`
                            metadata field. See our docs on [anonymous vs identified
                            events](https://posthog.com/docs/data/anonymous-vs-identified-events) to learn more.
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
