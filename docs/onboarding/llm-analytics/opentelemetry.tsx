import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getOpenTelemetrySteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, CalloutBox, Markdown, Blockquote, dedent, snippets } = ctx

    const NotableGenerationProperties = snippets?.NotableGenerationProperties

    return [
        {
            title: 'Install dependencies',
            badge: 'required',
            content: (
                <>
                    <CalloutBox type="info" icon="IconInfo" title="Using our SDKs? You probably don't need this page">
                        <Markdown>
                            If you're using our [Python](/docs/libraries/python) or [Node.js](/docs/libraries/node) SDKs
                            with a supported provider (OpenAI, Anthropic, Gemini, and more), use the [native
                            wrappers](/docs/llm-analytics/installation) instead. This page is for OpenTelemetry-native
                            setups, OpenTelemetry collectors, and frameworks that don't have a PostHog SDK wrapper yet.
                        </Markdown>
                    </CalloutBox>

                    <CalloutBox type="fyi" icon="IconInfo" title="Full working examples">
                        <Markdown>
                            The [Node.js](https://github.com/PostHog/posthog-js/tree/main/examples/example-ai-openai)
                            and
                            [Python](https://github.com/PostHog/posthog-python/tree/master/examples/example-ai-openai)
                            OpenAI examples show a complete end-to-end OpenTelemetry setup. Swap the instrumentation for
                            any other `gen_ai.*`-emitting library to trace a different provider or framework.
                        </Markdown>
                    </CalloutBox>

                    <Markdown>
                        Install the OpenTelemetry SDK, PostHog's OpenTelemetry helper, and an OpenTelemetry
                        instrumentation for the provider you want to trace. The examples below use the OpenAI
                        instrumentation, but any library that emits `gen_ai.*` spans will work.
                    </Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'Python',
                                code: dedent`
                                    pip install openai opentelemetry-sdk posthog[otel] opentelemetry-instrumentation-openai-v2
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'Node',
                                code: dedent`
                                    npm install openai @posthog/ai @opentelemetry/sdk-node @opentelemetry/resources @opentelemetry/instrumentation-openai
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
                        Configure OpenTelemetry to export spans to PostHog via the `PostHogSpanProcessor`. The processor
                        only forwards AI-related spans — spans whose name or attribute keys start with `gen_ai.`,
                        `llm.`, `ai.`, or `traceloop.` — and drops everything else. PostHog converts `gen_ai.*` spans
                        into `$ai_generation` events automatically.
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
                                `,
                            },
                            {
                                language: 'typescript',
                                file: 'Node',
                                code: dedent`
                                    import { NodeSDK } from '@opentelemetry/sdk-node'
                                    import { resourceFromAttributes } from '@opentelemetry/resources'
                                    import { PostHogSpanProcessor } from '@posthog/ai/otel'
                                    import { OpenAIInstrumentation } from '@opentelemetry/instrumentation-openai'

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
                                      instrumentations: [new OpenAIInstrumentation()],
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
            title: 'Make an LLM call',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        With the processor and instrumentation wired up, any LLM call made through the instrumented SDK
                        is captured. PostHog receives the emitted `gen_ai.*` span and converts it into an
                        `$ai_generation` event.
                    </Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'python',
                                file: 'Python',
                                code: dedent`
                                    import openai

                                    client = openai.OpenAI(api_key="<openai_api_key>")

                                    response = client.chat.completions.create(
                                        model="gpt-5-mini",
                                        messages=[
                                            {"role": "user", "content": "Tell me a fun fact about hedgehogs"}
                                        ],
                                    )

                                    print(response.choices[0].message.content)
                                `,
                            },
                            {
                                language: 'typescript',
                                file: 'Node',
                                code: dedent`
                                    import OpenAI from 'openai'

                                    const client = new OpenAI({ apiKey: '<openai_api_key>' })

                                    const response = await client.chat.completions.create({
                                      model: 'gpt-5-mini',
                                      messages: [{ role: 'user', content: 'Tell me a fun fact about hedgehogs' }],
                                    })

                                    console.log(response.choices[0].message.content)
                                `,
                            },
                        ]}
                    />

                    <Blockquote>
                        <Markdown>
                            {dedent`
                            **Note:** If you want to capture LLM events anonymously, omit the \`posthog.distinct_id\` resource attribute. See our docs on [anonymous vs identified events](https://posthog.com/docs/data/anonymous-vs-identified-events) to learn more.
                            `}
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
        {
            title: 'Send OTLP traces directly (advanced)',
            badge: 'optional',
            content: (
                <>
                    <Markdown>
                        If you already run an OpenTelemetry collector, or you want to export from a language other than
                        Python or Node.js, point any OTLP/HTTP exporter directly at PostHog's AI ingestion endpoint.
                        PostHog accepts OTLP over HTTP in both `application/x-protobuf` and `application/json`,
                        authenticated with a `Bearer` token.
                    </Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'Environment',
                                code: dedent`
                                    OTEL_EXPORTER_OTLP_TRACES_ENDPOINT="<ph_client_api_host>/i/v0/ai/otel"
                                    OTEL_EXPORTER_OTLP_TRACES_HEADERS="Authorization=Bearer <ph_project_token>"
                                `,
                            },
                            {
                                language: 'yaml',
                                file: 'Collector',
                                code: dedent`
                                    exporters:
                                      otlphttp/posthog:
                                        traces_endpoint: "<ph_client_api_host>/i/v0/ai/otel"
                                        headers:
                                          Authorization: "Bearer <ph_project_token>"

                                    service:
                                      pipelines:
                                        traces:
                                          receivers: [otlp]
                                          processors: [batch]
                                          exporters: [otlphttp/posthog]
                                `,
                            },
                        ]}
                    />

                    <Markdown>
                        The endpoint only ingests AI-related spans — those whose name or attribute keys start with
                        `gen_ai.`, `llm.`, `ai.`, or `traceloop.`. Every other span is dropped server-side, so it's safe
                        to send a mixed trace stream.
                    </Markdown>
                </>
            ),
        },
    ]
}

export const OpenTelemetryInstallation = createInstallation(getOpenTelemetrySteps)
