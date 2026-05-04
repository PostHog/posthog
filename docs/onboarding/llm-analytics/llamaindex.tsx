import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getLlamaIndexSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
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
                            example](https://github.com/PostHog/posthog-python/tree/master/examples/example-ai-llamaindex)
                            on GitHub. If you're using the PostHog SDK wrapper instead of OpenTelemetry, see the [Python
                            wrapper
                            example](https://github.com/PostHog/posthog-python/tree/7223c52/examples/example-ai-llamaindex).
                        </Markdown>
                    </CalloutBox>

                    <Markdown>
                        Install LlamaIndex, OpenAI, and the OpenTelemetry SDK with the LlamaIndex instrumentation.
                    </Markdown>

                    <CodeBlock
                        language="bash"
                        code={dedent`
                            pip install llama-index llama-index-llms-openai opentelemetry-sdk posthog[otel] opentelemetry-instrumentation-llamaindex
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
                        Configure OpenTelemetry to auto-instrument LlamaIndex calls and export traces to PostHog.
                        PostHog converts `gen_ai.*` spans into `$ai_generation` events automatically.
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            from opentelemetry import trace
                            from opentelemetry.sdk.trace import TracerProvider
                            from opentelemetry.sdk.resources import Resource, SERVICE_NAME
                            from posthog.ai.otel import PostHogSpanProcessor
                            from opentelemetry.instrumentation.llamaindex import LlamaIndexInstrumentor

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

                            LlamaIndexInstrumentor().instrument()
                        `}
                    />
                </>
            ),
        },
        {
            title: 'Query with LlamaIndex',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Use LlamaIndex as normal. The OpenTelemetry instrumentation automatically captures
                        `$ai_generation` events for each LLM call.
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            from llama_index.llms.openai import OpenAI
                            from llama_index.core import VectorStoreIndex, SimpleDirectoryReader

                            llm = OpenAI(model="gpt-4o-mini", api_key="your_openai_api_key")

                            # Load your documents
                            documents = SimpleDirectoryReader("data").load_data()

                            # Create an index
                            index = VectorStoreIndex.from_documents(documents, llm=llm)

                            # Query the index
                            query_engine = index.as_query_engine(llm=llm)
                            response = query_engine.query("What is this document about?")

                            print(response)
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

export const LlamaIndexInstallation = createInstallation(getLlamaIndexSteps)
