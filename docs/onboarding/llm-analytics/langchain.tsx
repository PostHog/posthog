import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getLangChainSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
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
                            See the complete
                            [Node.js](https://github.com/PostHog/posthog-js/tree/main/examples/example-ai-langchain) and
                            [Python](https://github.com/PostHog/posthog-python/tree/master/examples/example-ai-langchain)
                            examples on GitHub. If you're using the PostHog SDK wrapper instead of OpenTelemetry, see
                            the [Node.js
                            wrapper](https://github.com/PostHog/posthog-js/tree/e08ff1be/examples/example-ai-langchain)
                            and [Python
                            wrapper](https://github.com/PostHog/posthog-python/tree/7223c52/examples/example-ai-langchain)
                            examples.
                        </Markdown>
                    </CalloutBox>

                    <Markdown>
                        Install the OpenTelemetry SDK, the LangChain instrumentation, and LangChain with OpenAI.
                    </Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'Python',
                                code: dedent`
                                    pip install langchain langchain-core langchain-openai opentelemetry-sdk posthog[otel] opentelemetry-instrumentation-langchain
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'Node',
                                code: dedent`
                                    npm install langchain @langchain/core @langchain/openai @posthog/ai @opentelemetry/sdk-node @opentelemetry/resources @traceloop/instrumentation-langchain
                                `,
                            },
                        ]}
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
                        Configure OpenTelemetry to auto-instrument LangChain calls and export traces to PostHog. PostHog
                        converts `gen_ai.*` spans into `$ai_generation` events automatically.
                    </Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'python',
                                file: 'Python',
                                code: dedent`
                                    from opentelemetry import trace
                                    from opentelemetry.sdk.trace import TracerProvider
                                    from opentelemetry.sdk.resources import Resource, SERVICE_NAME
                                    from posthog.ai.otel import PostHogSpanProcessor
                                    from opentelemetry.instrumentation.langchain import LangchainInstrumentor

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

                                    LangchainInstrumentor().instrument()
                                `,
                            },
                            {
                                language: 'typescript',
                                file: 'Node',
                                code: dedent`
                                    import { NodeSDK } from '@opentelemetry/sdk-node'
                                    import { resourceFromAttributes } from '@opentelemetry/resources'
                                    import { PostHogSpanProcessor } from '@posthog/ai/otel'
                                    import { LangChainInstrumentation } from '@traceloop/instrumentation-langchain'

                                    const sdk = new NodeSDK({
                                      resource: resourceFromAttributes({
                                        'service.name': 'my-app',
                                        'posthog.distinct_id': 'user_123', // optional: identifies the user in PostHog
                                        foo: 'bar', // custom properties are passed through
                                      }),
                                      spanProcessors: [
                                        new PostHogSpanProcessor({
                                          apiKey: '<ph_project_token>',
                                          host: '<ph_client_api_host>',
                                        }),
                                      ],
                                      instrumentations: [new LangChainInstrumentation()],
                                    })
                                    sdk.start()
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Call LangChain',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Use LangChain as normal. The OpenTelemetry instrumentation automatically captures
                        `$ai_generation` events for each LLM call — no callback handlers needed.
                    </Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'python',
                                file: 'Python',
                                code: dedent`
                                    from langchain_openai import ChatOpenAI
                                    from langchain_core.prompts import ChatPromptTemplate

                                    prompt = ChatPromptTemplate.from_messages([
                                        ("system", "You are a helpful assistant."),
                                        ("user", "{input}")
                                    ])

                                    model = ChatOpenAI(openai_api_key="your_openai_api_key")
                                    chain = prompt | model

                                    response = chain.invoke({"input": "Tell me a joke about programming"})

                                    print(response.content)
                                `,
                            },
                            {
                                language: 'typescript',
                                file: 'Node',
                                code: dedent`
                                    import { ChatOpenAI } from '@langchain/openai'
                                    import { ChatPromptTemplate } from '@langchain/core/prompts'

                                    const prompt = ChatPromptTemplate.fromMessages([
                                      ["system", "You are a helpful assistant."],
                                      ["user", "{input}"]
                                    ])

                                    const model = new ChatOpenAI({ apiKey: "your_openai_api_key" })
                                    const chain = prompt.pipe(model)

                                    const response = await chain.invoke({ input: "Tell me a joke about programming" })

                                    console.log(response.content)
                                `,
                            },
                        ]}
                    />

                    <Blockquote>
                        <Markdown>
                            **Note:** If you want to capture LLM events anonymously, omit the `posthog.distinct_id`
                            resource attribute. See our docs on [anonymous vs identified
                            events](https://posthog.com/docs/data/anonymous-vs-identified-events) to learn more.
                        </Markdown>
                    </Blockquote>

                    <Markdown>
                        PostHog automatically captures an `$ai_generation` event along with these properties:
                    </Markdown>

                    {NotableGenerationProperties && <NotableGenerationProperties />}

                    <Markdown>
                        It also automatically creates a trace hierarchy based on how LangChain components are nested.
                    </Markdown>
                </>
            ),
        },
    ]
}

export const LangChainInstallation = createInstallation(getLangChainSteps)
