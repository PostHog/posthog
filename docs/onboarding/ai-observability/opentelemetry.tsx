import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'
import { getOtelSessionIdStep } from './_snippets/otel-session-id'

export const getOpenTelemetrySteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, CalloutBox, Markdown, Blockquote, dedent, snippets } = ctx

    const NotableGenerationProperties = snippets?.NotableGenerationProperties

    return [
        {
            title: 'Install dependencies',
            badge: 'required',
            content: (
                <>
                    <CalloutBox type="fyi" icon="IconInfo" title="Full working examples">
                        <Markdown>
                            The [Node.js](https://github.com/PostHog/posthog-js/tree/main/examples/example-ai-openai),
                            [Python](https://github.com/PostHog/posthog-python/tree/master/examples/example-ai-openai),
                            and [Go](https://github.com/PostHog/posthog-go/tree/main/otel/example) examples show a
                            complete end-to-end OpenTelemetry setup. Swap the instrumentation for any other
                            `gen_ai.*`-emitting library to trace a different provider or framework.
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
                                    pip install openai opentelemetry-sdk "posthog[otel]" opentelemetry-instrumentation-openai-v2
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'Node',
                                code: dedent`
                                    npm install openai @posthog/ai @opentelemetry/sdk-node @opentelemetry/resources @opentelemetry/instrumentation-openai
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'Go',
                                code: dedent`
                                    go get github.com/posthog/posthog-go/otel go.opentelemetry.io/otel go.opentelemetry.io/otel/sdk
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
                        Configure OpenTelemetry to export spans to PostHog via the `PostHogSpanProcessor`
                        (`posthogotel.NewSpanProcessor` in Go). The processor only forwards AI-related spans — spans
                        whose name or attribute keys start with `gen_ai.`, `llm.`, `ai.`, or `traceloop.` — and drops
                        everything else. PostHog converts `gen_ai.*` spans into `$ai_generation` events automatically.
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
                                          projectToken: '<ph_project_token>',
                                          host: '<ph_client_api_host>',
                                        }),
                                      ],
                                      instrumentations: [new OpenAIInstrumentation()],
                                    })
                                    sdk.start()
                                `,
                            },
                            {
                                language: 'go',
                                file: 'Go',
                                code: dedent`
                                    import (
                                        "context"

                                        posthogotel "github.com/posthog/posthog-go/otel"
                                        "go.opentelemetry.io/otel"
                                        "go.opentelemetry.io/otel/attribute"
                                        sdkresource "go.opentelemetry.io/otel/sdk/resource"
                                        sdktrace "go.opentelemetry.io/otel/sdk/trace"
                                    )

                                    func setupTracing(ctx context.Context) (*sdktrace.TracerProvider, error) {
                                        processor, err := posthogotel.NewSpanProcessor(ctx, "<ph_project_token>",
                                            posthogotel.WithHost("<ph_client_api_host>"),
                                        )
                                        if err != nil {
                                            return nil, err
                                        }

                                        resource := sdkresource.NewWithAttributes("",
                                            attribute.String("service.name", "my-app"),
                                            attribute.String("posthog.distinct_id", "user_123"), // optional: identifies the user in PostHog
                                            attribute.String("foo", "bar"), // custom properties are passed through
                                        )
                                        provider := sdktrace.NewTracerProvider(
                                            sdktrace.WithResource(resource),
                                            sdktrace.WithSpanProcessor(processor),
                                        )
                                        otel.SetTracerProvider(provider)
                                        return provider, nil
                                    }
                                `,
                            },
                        ]}
                    />

                    <Markdown>
                        {dedent`
                            In Go, if your app already has a \`TracerProvider\`, attach the processor to it with
                            \`provider.RegisterSpanProcessor(processor)\` instead of creating a new provider. Call
                            \`provider.Shutdown\` (or \`provider.ForceFlush\`) before exit so buffered spans are sent.
                        `}
                    </Markdown>
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

                    <Markdown>
                        {dedent`
                            Go has no instrumentation libraries for provider SDKs yet: start a span around each call
                            and set the \`gen_ai.*\` attributes yourself, as shown in the Go tab. Frameworks that
                            already emit \`gen_ai.*\` spans, like [ADK Go](https://google.golang.org/adk), are captured
                            automatically. ADK Go sends message content as log records rather than span attributes,
                            so its generations arrive without prompts and responses.
                        `}
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
                            {
                                language: 'go',
                                file: 'Go',
                                code: dedent`
                                    import (
                                        "go.opentelemetry.io/otel"
                                        "go.opentelemetry.io/otel/attribute"
                                        "go.opentelemetry.io/otel/codes"
                                    )

                                    tracer := otel.Tracer("my-app")
                                    _, span := tracer.Start(ctx, "chat gpt-5-mini")
                                    // Set the request attributes before the call so a failed call still
                                    // carries the gen_ai.* keys the PostHog span filter looks for
                                    span.SetAttributes(
                                        attribute.String("gen_ai.operation.name", "chat"),
                                        attribute.String("gen_ai.provider.name", "openai"),
                                        attribute.String("gen_ai.request.model", "gpt-5-mini"),
                                        // JSON-serialized chat messages
                                        attribute.String("gen_ai.input.messages", \`[{"role":"user","content":"Tell me a fun fact about hedgehogs"}]\`),
                                        attribute.String("server.address", "api.openai.com"),
                                    )

                                    resp, err := client.Chat.Completions.New(ctx, params) // your existing LLM call
                                    if err != nil {
                                        span.RecordError(err)
                                        // Status Error is what marks the event as a failed generation in PostHog
                                        span.SetStatus(codes.Error, err.Error())
                                        span.End()
                                        return err
                                    }

                                    span.SetAttributes(
                                        attribute.String("gen_ai.output.messages", \`[{"role":"assistant","content":"Hedgehogs have around 5,000 spines."}]\`),
                                        attribute.Int("gen_ai.usage.input_tokens", int(resp.Usage.PromptTokens)),
                                        attribute.Int("gen_ai.usage.output_tokens", int(resp.Usage.CompletionTokens)),
                                    )
                                    span.End()
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
            title: 'How attributes map to event properties',
            badge: 'recommended',
            content: (
                <>
                    <Markdown>
                        PostHog translates standard OpenTelemetry GenAI semantic convention attributes into the same
                        `$ai_*` event properties our native SDK wrappers emit, so traces look the same in PostHog
                        whether they arrive through OpenTelemetry or a native wrapper. The most common mappings:
                    </Markdown>

                    <Markdown>
                        {dedent`
                            | OpenTelemetry attribute | PostHog event property |
                            | --- | --- |
                            | \`gen_ai.response.model\` (or \`gen_ai.request.model\`) | \`$ai_model\` |
                            | \`gen_ai.provider.name\` (or \`gen_ai.system\`) | \`$ai_provider\` |
                            | \`gen_ai.input.messages\` | \`$ai_input\` |
                            | \`gen_ai.output.messages\` | \`$ai_output_choices\` |
                            | \`gen_ai.usage.input_tokens\` (or \`gen_ai.usage.prompt_tokens\`) | \`$ai_input_tokens\` |
                            | \`gen_ai.usage.output_tokens\` (or \`gen_ai.usage.completion_tokens\`) | \`$ai_output_tokens\` |
                            | \`server.address\` | \`$ai_base_url\` |
                            | \`telemetry.sdk.name\` / \`telemetry.sdk.version\` | \`$ai_lib\` / \`$ai_lib_version\` |
                            | Span start/end timestamps | \`$ai_latency\` (computed in seconds) |
                            | Span name | \`$ai_span_name\` |
                        `}
                    </Markdown>

                    <Markdown>Additional behavior worth knowing:</Markdown>

                    <Markdown>
                        {dedent`
                            - **Custom attributes pass through.** Any Resource or span attribute that isn't part of the known mapping is forwarded onto the event as-is, so you can add dimensions like \`conversation_id\` or \`tenant_id\` and filter on them in PostHog.
                            - **Trace and span IDs are preserved** as \`$ai_trace_id\`, \`$ai_span_id\`, and \`$ai_parent_id\`, so multi-step traces reconstruct correctly.
                            - **Events are classified by operation.** \`gen_ai.operation.name=chat\` becomes an \`$ai_generation\` event; \`embeddings\` becomes \`$ai_embedding\`. Spans without a recognized operation become \`$ai_span\` (or \`$ai_trace\` if they're the root of a trace).
                            - **Vercel AI SDK, Pydantic AI, and Traceloop/OpenLLMetry** emit their own namespaces (\`ai.*\`, \`pydantic_ai.*\`, \`traceloop.*\`) and PostHog normalizes those to the same \`$ai_*\` properties.
                            - **Noisy resource attributes are dropped.** OpenTelemetry auto-detected attributes under \`host.*\`, \`process.*\`, \`os.*\`, and \`telemetry.*\` (except \`telemetry.sdk.name\` / \`telemetry.sdk.version\`) don't pollute event properties.
                        `}
                    </Markdown>
                </>
            ),
        },
        getOtelSessionIdStep(ctx, { languages: ['Python', 'Node', 'Go'] }),
        {
            title: 'Other instrumentations, direct OTLP, and troubleshooting',
            badge: 'optional',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            **Alternative instrumentation libraries.** Any library that emits standard \`gen_ai.*\` spans (or \`ai.*\` / \`traceloop.*\` / \`pydantic_ai.*\`) works with the setup above. Swap \`@opentelemetry/instrumentation-openai\` / \`opentelemetry-instrumentation-openai-v2\` for one of these to broaden provider coverage:

                            - [OpenLIT](https://github.com/openlit/openlit) — single instrumentation that covers many providers, vector DBs, and frameworks.
                            - [OpenLLMetry](https://github.com/traceloop/openllmetry) (Traceloop) — broad provider and framework support in Python and JavaScript.
                            - [OpenInference](https://github.com/Arize-ai/openinference) (Arize) — provider- and framework-specific instrumentations for Python and JavaScript.
                            - [MLflow tracing](https://mlflow.org/docs/latest/llms/tracing/index.html) — if you already run MLflow.
                        `}
                    </Markdown>

                    <Markdown>
                        {dedent`
                            **Direct OTLP export.** If you run an OpenTelemetry Collector, or want to export from a language other than Python, Node.js, or Go, point any OTLP/HTTP exporter directly at PostHog's AI ingestion endpoint. PostHog accepts OTLP over HTTP in both \`application/x-protobuf\` and \`application/json\`, authenticated with a \`Bearer\` token. The endpoint is signal-specific (traces only), so use the \`OTEL_EXPORTER_OTLP_TRACES_*\` variants rather than the general \`OTEL_EXPORTER_OTLP_*\` ones (the SDK appends \`/v1/traces\` to the latter and would 404).
                        `}
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
                                    receivers:
                                      otlp:
                                        protocols:
                                          http:
                                            endpoint: 0.0.0.0:4318

                                    processors:
                                      batch:
                                      memory_limiter:
                                        check_interval: 5s
                                        limit_mib: 1500
                                        spike_limit_mib: 512

                                    exporters:
                                      otlphttp/posthog:
                                        traces_endpoint: "<ph_client_api_host>/i/v0/ai/otel"
                                        headers:
                                          Authorization: "Bearer <ph_project_token>"

                                    service:
                                      pipelines:
                                        traces:
                                          receivers: [otlp]
                                          processors: [memory_limiter, batch]
                                          exporters: [otlphttp/posthog]
                                `,
                            },
                        ]}
                    />

                    <Markdown>
                        {dedent`
                            **Limits and troubleshooting.**

                            - **Only AI spans are ingested.** Spans whose name and attribute keys don't start with \`gen_ai.\`, \`llm.\`, \`ai.\`, or \`traceloop.\` are dropped server-side, so it's safe to send a mixed trace stream.
                            - **HTTP only, no gRPC.** The endpoint speaks OTLP over HTTP in either \`application/x-protobuf\` or \`application/json\`. If your collector or SDK is configured for gRPC, switch to HTTP.
                            - **Request body is capped at 4 MB.** Large or unbounded traces (for example, long chat histories with base64-encoded images) can exceed this. Use a collector with the \`batch\` processor to keep individual exports small.
                            - **Missing traces?** Make sure you're pointing at the traces-specific OTLP variable (\`OTEL_EXPORTER_OTLP_TRACES_ENDPOINT\` / \`traces_endpoint\`) rather than the general one, and that your project token is set correctly in the \`Authorization: Bearer\` header.
                        `}
                    </Markdown>
                </>
            ),
        },
    ]
}

export const OpenTelemetryInstallation = createInstallation(getOpenTelemetrySteps)
