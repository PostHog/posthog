import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getSmolagentsSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
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
                            example](https://github.com/PostHog/posthog-python/tree/master/examples/example-ai-smolagents)
                            on GitHub. If you're using the PostHog SDK wrapper instead of OpenTelemetry, see the [Python
                            wrapper
                            example](https://github.com/PostHog/posthog-python/tree/7223c52/examples/example-ai-smolagents).
                        </Markdown>
                    </CalloutBox>

                    <Markdown>Install the OpenTelemetry SDK, the OpenAI instrumentation, and smolagents.</Markdown>

                    <CodeBlock
                        language="bash"
                        code={dedent`
                            pip install smolagents openai opentelemetry-sdk "posthog[otel]" opentelemetry-instrumentation-openai-v2
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
                                \`$ai_session_id\` groups multiple traces into one PostHog session, and with this
                                integration the only place to set it is a \`Resource\` attribute fixed when the
                                OpenTelemetry SDK starts. That works if a process only ever runs one agent
                                conversation, like a script, but a long-lived smolagents service ends up stamping
                                every user's run with the same session id — silently, since nothing about the setup
                                errors.

                                For sessions scoped to one conversation, capture \`$ai_span\` and \`$ai_generation\`
                                events directly (see
                                [manual capture](https://posthog.com/docs/ai-observability/installation/manual-capture)),
                                or move to an integration with a per-call channel, such as the PostHog SDK wrappers or
                                the
                                [LangChain callback handler](https://posthog.com/docs/ai-observability/installation/langchain).

                                It's also worth knowing this only captures the model calls smolagents makes — not any
                                tools you add to that \`tools=[]\` list. Give a tool call its own \`$ai_span\`, tied to
                                the same \`$ai_trace_id\`, if you want it to show up.
                            `}
                        </Markdown>
                    </CalloutBox>
                </>
            ),
        },
        {
            title: 'Run your agent',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Use smolagents as normal. PostHog automatically captures an `$ai_generation` event for each LLM
                        call made through the OpenAI SDK that smolagents uses internally.
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            import os
                            from smolagents import CodeAgent, LiteLLMModel

                            model = LiteLLMModel(model_id="gpt-4o-mini", api_key=os.environ["OPENAI_API_KEY"])
                            agent = CodeAgent(tools=[], model=model)

                            result = agent.run("Tell me a fun fact about hedgehogs")
                            print(result)
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

export const SmolagentsInstallation = createInstallation(getSmolagentsSteps)
