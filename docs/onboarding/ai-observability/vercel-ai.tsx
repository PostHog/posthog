import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

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
                                  apiKey: '<ph_project_token>',
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
                                  posthog_environment: 'production', // custom property: sets "environment" on the event
                                  $ai_session_id: 'conversation-abc', // optional: groups calls into one session
                                },
                              },
                            })

                            console.log(result.text)
                        `}
                    />

                    <Markdown>
                        Pass `$ai_session_id` in `metadata` to group every call in a conversation into one PostHog
                        session.
                    </Markdown>

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
                            the `$ai_generation` event as a custom property. The prefix is stripped, so
                            `posthog_environment` becomes an `environment` property you can filter and break down by.
                            Other metadata fields aren't captured.
                        </Markdown>
                    </Blockquote>

                    <CalloutBox type="caution" icon="IconWarning" title="Tool calls aren't fully captured">
                        <Markdown>
                            {dedent`
                                PostHog's ingestion strips \`ai.prompt.tools\` and \`ai.response.toolCalls\` from the
                                spans this integration emits, so \`$ai_tools\` isn't populated and the model's
                                requested tool calls don't reach \`$ai_output_choices\`. Tool executions still appear
                                as \`$ai_span\` events. If you need full tool-call visibility, use
                                [OpenTelemetry](https://posthog.com/docs/ai-observability/installation/opentelemetry)
                                instead.
                            `}
                        </Markdown>
                    </CalloutBox>

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
