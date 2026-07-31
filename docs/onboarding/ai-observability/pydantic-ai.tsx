import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getPydanticAISteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
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
                            example](https://github.com/PostHog/posthog-python/tree/master/examples/example-ai-pydantic-ai)
                            on GitHub. If you're using the PostHog SDK wrapper instead of OpenTelemetry, see the [Python
                            wrapper
                            example](https://github.com/PostHog/posthog-python/tree/7223c52/examples/example-ai-pydantic-ai).
                        </Markdown>
                    </CalloutBox>

                    <Markdown>Install the OpenTelemetry SDK and Pydantic AI.</Markdown>

                    <CodeBlock
                        language="bash"
                        code={dedent`
                            pip install "pydantic-ai[openai]" opentelemetry-sdk "posthog[otel]"
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
                        Configure OpenTelemetry to export traces to PostHog and enable Pydantic AI's built-in OTel
                        instrumentation. PostHog converts `gen_ai.*` spans into `$ai_generation` events automatically.
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            import os
                            from opentelemetry import trace
                            from opentelemetry.sdk.trace import TracerProvider
                            from opentelemetry.sdk.resources import Resource, SERVICE_NAME
                            from posthog.ai.otel import PostHogSpanProcessor
                            from pydantic_ai import Agent

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

                            # Enable automatic OTel instrumentation for all Pydantic AI agents
                            Agent.instrument_all()
                        `}
                    />

                    <CalloutBox type="caution" icon="IconWarning" title="Session grouping">
                        <Markdown>
                            {dedent`
                                Unlike the other integrations on this page, Pydantic AI's built-in OpenTelemetry
                                instrumentation gives you a genuine span tree, not one flat span per call —
                                \`Agent.instrument_all()\` emits an \`invoke_agent\` span for the run itself, alongside
                                the \`gen_ai.*\` span for the model call, so PostHog can reconstruct the agent run
                                rather than just the LLM call inside it.

                                Session grouping is the one place this setup still falls short, same as the rest.
                                \`$ai_session_id\` can only be set as a \`Resource\` attribute when \`TracerProvider\`
                                is created, and that's fixed for the process's lifetime — fine for a script or a
                                one-conversation-per-process worker, wrong for a long-lived agent service, where every
                                conversation silently collapses into the same session.

                                For a session id per conversation, capture \`$ai_span\` and \`$ai_generation\` events
                                directly (see
                                [manual capture](https://posthog.com/docs/ai-observability/installation/manual-capture)),
                                or use an integration with a per-call channel, such as the PostHog SDK wrappers or the
                                [LangChain callback handler](https://posthog.com/docs/ai-observability/installation/langchain).
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
                        Create a Pydantic AI agent and run it. PostHog automatically captures an `$ai_generation` event
                        for each LLM call via the OTel instrumentation.
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            from pydantic_ai import Agent
                            from pydantic_ai.models.openai import OpenAIModel

                            model = OpenAIModel("gpt-4o-mini")
                            agent = Agent(model, system_prompt="You are a helpful assistant.")

                            result = agent.run_sync("Tell me a fun fact about hedgehogs.")
                            print(result.output)
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

export const PydanticAIInstallation = createInstallation(getPydanticAISteps)
