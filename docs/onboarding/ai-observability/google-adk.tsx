import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getGoogleADKSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, CalloutBox, Markdown, dedent, snippets } = ctx
    const NotableGenerationProperties = snippets?.NotableGenerationProperties

    return [
        {
            title: 'Install dependencies',
            badge: 'required',
            content: (
                <>
                    <CalloutBox type="fyi" icon="IconInfo" title="Full working example">
                        <Markdown>
                            See the complete [Node.js
                            example](https://github.com/PostHog/posthog-js/tree/main/examples/example-ai-adk) on GitHub.
                        </Markdown>
                    </CalloutBox>

                    <Markdown>
                        Install the PostHog SDK alongside the [Google Agent Development Kit for
                        TypeScript](https://github.com/google/adk-js) (`@google/adk`). For the Python and Go ADKs, use
                        the [OpenTelemetry
                        integration](https://posthog.com/docs/ai-observability/installation/opentelemetry) instead: they
                        emit `gen_ai.*` spans that PostHog captures automatically. ADK Go sends message content as log
                        records, so its generations arrive without prompts and responses.
                    </Markdown>

                    <CodeBlock
                        language="bash"
                        code={dedent`
                            npm install @posthog/ai posthog-node @google/adk zod
                        `}
                    />
                </>
            ),
        },
        {
            title: 'Add the PostHog plugin',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Create a PostHog client and register `PostHogADKPlugin` on your ADK `Runner`. The plugin hooks
                        the run, agent, tool, and model callbacks and captures the full hierarchy: an `$ai_trace` per
                        invocation, `$ai_span` events for agent runs and tool calls, and one `$ai_generation` per model
                        call. It **does not** proxy your calls.
                    </Markdown>

                    <CodeBlock
                        language="typescript"
                        code={dedent`
                            import { FunctionTool, InMemorySessionService, LlmAgent, Runner } from '@google/adk'
                            import { PostHogADKPlugin } from '@posthog/ai/adk'
                            import { PostHog } from 'posthog-node'
                            import { z } from 'zod'

                            const posthog = new PostHog('<ph_project_token>', { host: '<ph_client_api_host>' })

                            const getWeather = new FunctionTool({
                              name: 'get_weather',
                              description: 'Get the current weather for a city.',
                              parameters: z.object({ city: z.string() }),
                              execute: ({ city }) => \`The weather in \${city} is sunny, 72F\`,
                            })

                            const agent = new LlmAgent({
                              name: 'assistant',
                              model: 'gemini-3.6-flash',
                              instruction: 'You are a helpful assistant.',
                              tools: [getWeather],
                            })

                            const sessionService = new InMemorySessionService()
                            const runner = new Runner({
                              appName: 'my-app',
                              agent,
                              sessionService,
                              plugins: [new PostHogADKPlugin({ client: posthog })],
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
                        {dedent`
                            Run your agent as normal. Each invocation becomes a trace, the ADK session ID becomes
                            \`$ai_session_id\`, and the run's \`userId\` becomes the events' distinct ID. Pass
                            \`distinctId\` to the plugin to attribute events to a different PostHog person.
                        `}
                    </Markdown>

                    <CodeBlock
                        language="typescript"
                        code={dedent`
                            await sessionService.createSession({
                              appName: 'my-app',
                              userId: 'user_123',
                              sessionId: 'conversation-abc',
                            })

                            for await (const event of runner.runAsync({
                              userId: 'user_123',
                              sessionId: 'conversation-abc',
                              newMessage: { role: 'user', parts: [{ text: "What's the weather in Paris?" }] },
                            })) {
                              for (const part of event.content?.parts ?? []) {
                                if (part.text) {
                                  console.log(part.text)
                                }
                              }
                            }
                        `}
                    />

                    <Markdown>
                        {dedent`
                            The question above makes the agent call the tool, so this run captures:

                            - a trace for the invocation
                            - a span for the \`assistant\` agent run
                            - a span for the \`get_weather\` tool call
                            - a generation for each of the two model calls (the tool request, then the answer)
                        `}
                    </Markdown>

                    <Markdown>
                        Call `await posthog.shutdown()` before your process exits so batched events are flushed.
                    </Markdown>

                    <Markdown>
                        {dedent`
                            You can expect captured \`$ai_generation\` events to have the following properties:
                        `}
                    </Markdown>

                    {NotableGenerationProperties && <NotableGenerationProperties />}
                </>
            ),
        },
        {
            title: 'Plugin options',
            badge: 'optional',
            content: (
                <Markdown>
                    {dedent`
                        \`PostHogADKPlugin\` accepts these options besides \`client\`:

                        - \`distinctId\`: a string, or a resolver \`(context) => string\` called per model call. Defaults to the ADK \`userId\`.
                        - \`provider\`: the \`$ai_provider\` label. Defaults to \`gemini\`. Set it when routing ADK to another provider so costs are derived from the right model catalog.
                        - \`privacyMode\`: redacts captured input and output content.
                        - \`groups\`: [group analytics](https://posthog.com/docs/product-analytics/group-analytics) attached to every event.
                        - \`properties\`: extra properties merged into every event.
                        - \`captureImmediate\`: awaits delivery per event instead of batching. Useful in serverless environments.
                        - \`onError\`: called when capturing an event fails. Capture errors never throw into the model flow.
                    `}
                </Markdown>
            ),
        },
    ]
}

export const GoogleADKInstallation = createInstallation(getGoogleADKSteps)
