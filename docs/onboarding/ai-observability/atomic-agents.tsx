import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getAtomicAgentsSteps = (context: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, CalloutBox, Markdown, dedent } = context

    return [
        {
            title: 'Install dependencies',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        [Atomic Agents](https://github.com/eigenwise/atomic-agents) emits OpenTelemetry spans for agent
                        runs, tool runs, and each Instructor completion attempt. Install its tracing extra, the
                        OpenTelemetry SDK, and the HTTP exporter. The example uses OpenAI through Instructor.
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                code: dedent`
                                    pip install "atomic-agents[observability]>=2.15.0,<3" opentelemetry-sdk opentelemetry-exporter-otlp-proto-http openai
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
                    <CalloutBox
                        type="fyi"
                        icon="IconInfo"
                        title="Message content is unavailable in Atomic Agents 2.15.0"
                    >
                        <Markdown>
                            Atomic Agents 2.15.0 does not emit `gen_ai.input.messages` or `gen_ai.output.messages`.
                            PostHog receives model, token usage, timing, and span relationships, but generation prompts
                            and responses are empty. The setup below also hides agent and tool payloads. Disabling those
                            privacy settings does not add the missing generation message attributes.
                        </Markdown>
                    </CalloutBox>
                    <Markdown>
                        Set your project token and client API host from [project
                        settings](https://app.posthog.com/settings/project). Use `https://us.i.posthog.com` for US Cloud
                        or `https://eu.i.posthog.com` for EU Cloud. Use a project token, which starts with `phc_`,
                        rather than a personal API key.
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                code: dedent`
                                    export POSTHOG_HOST="<ph_client_api_host>"
                                    export POSTHOG_PROJECT_TOKEN="<ph_project_token>"
                                    export OPENAI_API_KEY="<openai_api_key>"
                                `,
                            },
                            {
                                language: 'python',
                                code: dedent`
                                    import os

                                    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
                                    from opentelemetry.sdk.resources import Resource
                                    from opentelemetry.sdk.trace import TracerProvider
                                    from opentelemetry.sdk.trace.export import BatchSpanProcessor

                                    from atomic_agents.observability import AtomicAgentsInstrumentor, TracingConfig

                                    provider = TracerProvider(
                                        resource=Resource.create({"service.name": "atomic-agents-example"})
                                    )
                                    exporter = OTLPSpanExporter(
                                        endpoint=f"{os.environ['POSTHOG_HOST'].rstrip('/')}/i/v0/ai/otel",
                                        headers={"Authorization": f"Bearer {os.environ['POSTHOG_PROJECT_TOKEN']}"},
                                    )
                                    provider.add_span_processor(BatchSpanProcessor(exporter))
                                    AtomicAgentsInstrumentor().instrument(
                                        tracer_provider=provider,
                                        config=TracingConfig(hide_inputs=True, hide_outputs=True),
                                    )
                                `,
                            },
                        ]}
                    />
                    <Markdown>
                        Run this setup before your first agent call. If your app already has a tracer provider, add the
                        processor to that provider and pass it to the instrumentor. The AI ingestion endpoint is
                        `/i/v0/ai/otel` and accepts OTLP over HTTP, not gRPC.
                    </Markdown>
                    <Markdown>
                        Keep Atomic Agents' LLM attempt spans enabled for this setup. No separate OpenAI instrumentor is
                        needed. If your app already instruments provider calls, choose one LLM instrumentation path to
                        avoid duplicate generations. See the [OpenTelemetry
                        guide](/docs/ai-observability/installation/opentelemetry) for other exporter configurations.
                    </Markdown>
                </>
            ),
        },
        {
            title: 'Run an agent',
            badge: 'required',
            content: (
                <>
                    <Markdown>Add this code after the tracing setup in the same Python file.</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'python',
                                code: dedent`
                                    import instructor
                                    from openai import OpenAI

                                    from atomic_agents import AgentConfig, AtomicAgent, BasicChatInputSchema, BasicChatOutputSchema

                                    client = instructor.from_openai(OpenAI(), mode=instructor.Mode.JSON)
                                    agent = AtomicAgent[BasicChatInputSchema, BasicChatOutputSchema](
                                        AgentConfig(
                                            client=client,
                                            model="gpt-5-mini",
                                            mode=instructor.Mode.JSON,
                                            name="assistant",
                                        )
                                    )
                                    try:
                                        result = agent.run(BasicChatInputSchema(chat_message="What is a typed agent pipeline?"))
                                        print(result.chat_message)
                                    finally:
                                        provider.shutdown()
                                `,
                            },
                        ]}
                    />
                    <Markdown>
                        Each agent run creates an `invoke_agent assistant` span. Its `chat gpt-5-mini` child represents
                        an Instructor attempt. Retries create additional attempt spans. Tools create `execute_tool`
                        spans when used. PostHog maps chat spans to generations and agent or tool spans to spans.
                    </Markdown>
                    <Markdown>
                        This short script shuts down the provider to flush buffered spans before exit. In a service,
                        keep the provider running and shut it down during application shutdown. Check the Traces and
                        Generations tabs in AI Observability. Token counts depend on the provider returning usage.
                        Prompts and responses remain empty with Atomic Agents 2.15.0.
                    </Markdown>
                </>
            ),
        },
    ]
}

export const AtomicAgentsInstallation = createInstallation(getAtomicAgentsSteps)
