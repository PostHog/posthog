import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getAutoGenSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
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
                            See the complete [Python
                            example](https://github.com/PostHog/posthog-python/tree/master/examples/example-ai-autogen)
                            on GitHub. If you're using the PostHog SDK wrapper instead of OpenTelemetry, see the [Python
                            wrapper
                            example](https://github.com/PostHog/posthog-python/tree/7223c52/examples/example-ai-autogen).
                        </Markdown>
                    </CalloutBox>

                    <Markdown>Install the OpenTelemetry SDK, the OpenAI instrumentation, and AutoGen.</Markdown>

                    <CodeBlock
                        language="bash"
                        code={dedent`
                            pip install autogen-agentchat "autogen-ext[openai]" openai opentelemetry-sdk "posthog[otel]" opentelemetry-instrumentation-openai-v2
                        `}
                    />
                </>
            ),
        },
        {
            title: 'Set up OpenTelemetry tracing',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Configure OpenTelemetry to auto-instrument OpenAI SDK calls and export traces to PostHog.
                        PostHog converts `gen_ai.*` spans into `$ai_generation` events automatically.
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            from opentelemetry import trace
                            from opentelemetry.sdk.trace import TracerProvider
                            from opentelemetry.sdk.resources import Resource, SERVICE_NAME
                            from posthog.ai.otel import PostHogSpanProcessor
                            from opentelemetry.instrumentation.openai_v2 import OpenAIInstrumentor

                            resource = Resource(attributes={
                                SERVICE_NAME: "my-app",
                                "posthog.distinct_id": "user_123", # optional: identifies the user in PostHog
                                "foo": "bar", # custom properties are passed through
                            })

                            provider = TracerProvider(resource=resource)
                            provider.add_span_processor(
                                PostHogSpanProcessor(
                                    api_key="<ph_project_token>",
                                    host="<ph_client_api_host>",
                                )
                            )
                            trace.set_tracer_provider(provider)

                            OpenAIInstrumentor().instrument()
                        `}
                    />

                    <CalloutBox type="caution" icon="IconWarning" title="Session grouping">
                        <Markdown>
                            {dedent`
                                \`$ai_session_id\` is what groups every trace from one conversation into a single
                                PostHog session, but this integration only exposes it as an attribute on the
                                \`Resource\` built above — fixed the moment \`TracerProvider\` is created and never
                                touched again. That's accurate if a process only ever handles one conversation, like a
                                script, but a long-running AutoGen service ends up stamping every user's conversation
                                with the same session id. Nothing errors — the events are just grouped wrong.

                                For a session id per conversation, capture \`$ai_span\` and \`$ai_generation\` events
                                directly (see
                                [manual capture](https://posthog.com/docs/ai-observability/installation/manual-capture)),
                                or use an integration with a per-call channel instead, such as the PostHog SDK
                                wrappers or the
                                [LangChain callback handler](https://posthog.com/docs/ai-observability/installation/langchain).

                                This setup also only captures the OpenAI calls AutoGen's agents make under the hood —
                                not the tools those agents invoke. Give a tool call its own \`$ai_span\`, tied to the
                                same \`$ai_trace_id\`, if you want it to show up in the trace.
                            `}
                        </Markdown>
                    </CalloutBox>
                </>
            ),
        },
        {
            title: 'Run your agents',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Use AutoGen as normal. PostHog automatically captures an `$ai_generation` event for each LLM
                        call made through the OpenAI SDK that AutoGen uses internally.
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            import asyncio
                            from autogen_agentchat.agents import AssistantAgent
                            from autogen_ext.models.openai import OpenAIChatCompletionClient

                            model_client = OpenAIChatCompletionClient(
                                model="gpt-4o",
                                api_key="your_openai_api_key",
                            )
                            agent = AssistantAgent("assistant", model_client=model_client)

                            async def main():
                                result = await agent.run(task="Say 'Hello World!'")
                                print(result)
                                await model_client.close()

                            asyncio.run(main())
                        `}
                    />

                    <Blockquote>
                        <Markdown>
                            **Note:** If you want to capture LLM events anonymously, omit the `posthog.distinct_id`
                            resource attribute. See our docs on [anonymous vs identified
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

export const AutoGenInstallation = createInstallation(getAutoGenSteps)
