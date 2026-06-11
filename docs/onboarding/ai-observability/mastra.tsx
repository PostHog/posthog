import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getMastraSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, CalloutBox, Markdown, Blockquote, dedent, snippets } = ctx

    const NotableGenerationProperties = snippets?.NotableGenerationProperties

    return [
        {
            title: 'Install dependencies',
            badge: 'required',
            content: (
                <>
                    <CalloutBox type="info" icon="IconInfo" title="Full working examples">
                        <Markdown>
                            See the complete [Node.js
                            example](https://github.com/PostHog/posthog-js/tree/main/examples/example-ai-mastra) on
                            GitHub. If you're using the PostHog SDK wrapper instead, see the [Node.js wrapper
                            example](https://github.com/PostHog/posthog-js/tree/e08ff1be/examples/example-ai-mastra).
                        </Markdown>
                    </CalloutBox>

                    <Markdown>
                        Install Mastra with the official `@mastra/posthog` exporter. Mastra's observability system sends
                        traces to PostHog as `$ai_generation` events automatically.
                    </Markdown>

                    <CodeBlock
                        language="bash"
                        code={dedent`
                            npm install @mastra/core @mastra/observability @mastra/posthog
                        `}
                    />
                </>
            ),
        },
        {
            title: 'Configure Mastra with the PostHog exporter',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Initialize Mastra with an `Observability` config that uses the `PosthogExporter`. Pass your
                        PostHog project token and host from [your project
                        settings](https://app.posthog.com/settings/project).
                    </Markdown>

                    <CodeBlock
                        language="typescript"
                        code={dedent`
                            import { Mastra } from '@mastra/core'
                            import { Agent } from '@mastra/core/agent'
                            import { Observability } from '@mastra/observability'
                            import { PosthogExporter } from '@mastra/posthog'

                            const weatherAgent = new Agent({
                              id: 'weather-agent',
                              name: 'Weather Agent',
                              instructions: 'You are a helpful assistant with access to weather data.',
                              model: { id: 'openai/gpt-4o-mini' },
                            })

                            const mastra = new Mastra({
                              agents: { weatherAgent },
                              observability: new Observability({
                                configs: {
                                  posthog: {
                                    serviceName: 'my-app',
                                    exporters: [
                                      new PosthogExporter({
                                        apiKey: '<ph_project_token>',
                                        host: '<ph_client_api_host>',
                                        defaultDistinctId: 'user_123', // fallback if no userId in metadata
                                      }),
                                    ],
                                  },
                                },
                              }),
                            })
                        `}
                    />
                </>
            ),
        },
        {
            title: 'Run your agent',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Use Mastra as normal. The `PosthogExporter` automatically captures `$ai_generation` events for
                        each LLM call, including token usage, cost, latency, and the full conversation.
                    </Markdown>

                    <Markdown>
                        Pass `tracingOptions.metadata` to `generate()` to attach per-request metadata. The `userId`
                        field maps to PostHog's distinct ID, `sessionId` maps to `$ai_session_id`, and any other keys
                        are passed through as custom event properties.
                    </Markdown>

                    <CodeBlock
                        language="typescript"
                        code={dedent`
                            const agent = mastra.getAgent('weatherAgent')

                            const result = await agent.generate("What's the weather in Dublin?", {
                              tracingOptions: {
                                metadata: {
                                  userId: 'user_123', // becomes distinct_id
                                  sessionId: 'session_abc', // becomes $ai_session_id
                                  conversation_id: 'abc-123', // custom property
                                },
                              },
                            })

                            console.log(result.text)
                        `}
                    />

                    <Blockquote>
                        <Markdown>
                            **Note:** If you want to capture LLM events anonymously, omit `userId` from
                            `tracingOptions.metadata` and don't set `defaultDistinctId`. See our docs on [anonymous vs
                            identified events](https://posthog.com/docs/data/anonymous-vs-identified-events) to learn
                            more.
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

export const MastraInstallation = createInstallation(getMastraSteps)
