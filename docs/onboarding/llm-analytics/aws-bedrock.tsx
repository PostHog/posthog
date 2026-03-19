import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getAWSBedrockSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, CalloutBox, Markdown, Blockquote, dedent, snippets } = ctx

    const NotableGenerationProperties = snippets?.NotableGenerationProperties

    return [
        {
            title: 'Install dependencies',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Install the OpenTelemetry SDK, OTLP exporter, and the AWS SDK instrumentation for your language.
                    </Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'Python',
                                code: dedent`
                                    pip install boto3 opentelemetry-instrumentation-botocore opentelemetry-sdk opentelemetry-exporter-otlp-proto-http
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'Node',
                                code: dedent`
                                    npm install @aws-sdk/client-bedrock-runtime @opentelemetry/instrumentation-aws-sdk @opentelemetry/sdk-node @opentelemetry/resources @posthog/ai
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Set up the OpenTelemetry exporter',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Configure the OpenTelemetry SDK to export traces to PostHog's OTLP ingestion endpoint. PostHog
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
                                    from opentelemetry.sdk.trace.export import BatchSpanProcessor
                                    from opentelemetry.sdk.resources import Resource, SERVICE_NAME
                                    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
                                    from opentelemetry.instrumentation.botocore import BotocoreInstrumentor

                                    resource = Resource(attributes={
                                        SERVICE_NAME: "my-ai-app",
                                    })

                                    exporter = OTLPSpanExporter(
                                        endpoint="<ph_client_api_host>/i/v0/ai/otel",
                                        headers={"Authorization": "Bearer <ph_project_token>"},
                                    )

                                    provider = TracerProvider(resource=resource)
                                    provider.add_span_processor(BatchSpanProcessor(exporter))
                                    trace.set_tracer_provider(provider)

                                    BotocoreInstrumentor().instrument()
                                `,
                            },
                            {
                                language: 'typescript',
                                file: 'Node',
                                code: dedent`
                                    import { NodeSDK } from '@opentelemetry/sdk-node'
                                    import { resourceFromAttributes } from '@opentelemetry/resources'
                                    import { PostHogTraceExporter } from '@posthog/ai/otel'
                                    import { AwsInstrumentation } from '@opentelemetry/instrumentation-aws-sdk'

                                    const sdk = new NodeSDK({
                                      resource: resourceFromAttributes({
                                        'service.name': 'my-ai-app',
                                      }),
                                      traceExporter: new PostHogTraceExporter({
                                        apiKey: '<ph_project_token>',
                                        host: '<ph_client_api_host>',
                                      }),
                                      instrumentations: [new AwsInstrumentation()],
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
            title: 'Call Bedrock',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Make Bedrock API calls as normal. The instrumentation automatically captures `gen_ai.*` spans
                        for Converse, ConverseStream, InvokeModel, and InvokeModelWithResponseStream operations.
                    </Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'python',
                                file: 'Python',
                                code: dedent`
                                    import boto3

                                    client = boto3.client("bedrock-runtime", region_name="us-east-1")

                                    response = client.converse(
                                        modelId="us.anthropic.claude-3-5-haiku-20241022-v1:0",
                                        messages=[
                                            {
                                                "role": "user",
                                                "content": [{"text": "Tell me a fun fact about hedgehogs."}],
                                            }
                                        ],
                                    )

                                    print(response["output"]["message"]["content"][0]["text"])
                                `,
                            },
                            {
                                language: 'typescript',
                                file: 'Node',
                                code: dedent`
                                    // The AWS SDK must be imported after sdk.start() so the
                                    // instrumentation can patch it.
                                    const {
                                      BedrockRuntimeClient,
                                      ConverseCommand,
                                    } = await import('@aws-sdk/client-bedrock-runtime')

                                    const client = new BedrockRuntimeClient({ region: 'us-east-1' })

                                    const response = await client.send(
                                      new ConverseCommand({
                                        modelId: 'us.anthropic.claude-3-5-haiku-20241022-v1:0',
                                        messages: [
                                          {
                                            role: 'user',
                                            content: [{ text: 'Tell me a fun fact about hedgehogs.' }],
                                          },
                                        ],
                                      })
                                    )

                                    console.log(response.output?.message?.content?.[0]?.text)

                                    await sdk.shutdown()
                                `,
                            },
                        ]}
                    />

                    <CalloutBox type="fyi" icon="IconInfo" title="Supported models">
                        <Markdown>
                            The instrumentation emits `gen_ai.*` spans for **Amazon Titan**, **Amazon Nova**, and
                            **Anthropic Claude** models. Tool call instrumentation is available for Amazon Nova and
                            Anthropic Claude 3+.
                        </Markdown>
                    </CalloutBox>

                    <Blockquote>
                        <Markdown>
                            **Note:** If you want to capture LLM events anonymously, omit the `posthog_distinct_id`. See
                            our docs on [anonymous vs identified
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

export const AWSBedrockInstallation = createInstallation(getAWSBedrockSteps)
