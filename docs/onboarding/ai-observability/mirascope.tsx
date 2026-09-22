import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'
import { getOtelSessionIdStep } from './_snippets/otel-session-id'

export const getMirascopeSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
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
                            example](https://github.com/PostHog/posthog-python/tree/master/examples/example-ai-mirascope)
                            on GitHub. If you use the PostHog SDK wrapper instead of OpenTelemetry, see the [Python
                            wrapper
                            example](https://github.com/PostHog/posthog-python/tree/7223c52/examples/example-ai-mirascope).
                        </Markdown>
                    </CalloutBox>

                    <Markdown>Install the OpenTelemetry SDK, the OpenAI instrumentation, and Mirascope.</Markdown>

                    <CodeBlock
                        language="bash"
                        code={dedent`
                            pip install "mirascope[openai]" opentelemetry-sdk "posthog[otel]" opentelemetry-instrumentation-openai-v2
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
                </>
            ),
        },
        {
            title: 'Call your LLMs',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Use Mirascope as normal. PostHog automatically captures an `$ai_generation` event for each LLM
                        call made through the OpenAI SDK that Mirascope uses internally.
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            from mirascope import llm

                            # Route OpenAI calls through chat.completions. Mirascope defaults to the
                            # Responses API, which the OpenTelemetry instrumentation does not cover.
                            llm.register_provider("openai:completions")

                            @llm.call("openai/gpt-4o-mini")
                            def fun_fact(topic: str) -> str:
                                return f"Tell me a fun fact about {topic}"

                            response = fun_fact("hedgehogs")
                            print(response.text())
                        `}
                    />

                    <CalloutBox type="caution" icon="IconWarning" title="Use the completions provider">
                        <Markdown>
                            `opentelemetry-instrumentation-openai-v2` instruments `chat.completions` and `embeddings`
                            only. Mirascope v2 uses the OpenAI Responses API by default, which produces no spans.
                            `llm.register_provider("openai:completions")` switches it to `chat.completions`, so the
                            instrumentation captures the calls. This page targets Mirascope 2.x. The `mirascope.core`
                            API was v1 and no longer exists.
                        </Markdown>
                    </CalloutBox>

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
        getOtelSessionIdStep(ctx, { languages: ['Python'] }),
    ]
}

export const MirascopeInstallation = createInstallation(getMirascopeSteps)
