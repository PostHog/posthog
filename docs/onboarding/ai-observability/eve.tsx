import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getEveSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { Blockquote, CalloutBox, CodeBlock, Markdown, dedent, snippets } = ctx

    const NotableGenerationProperties = snippets?.NotableGenerationProperties

    return [
        {
            title: 'Install dependencies',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Install the PostHog AI exporter, OpenTelemetry HTTP exporter, and Vercel's OpenTelemetry
                        package.
                    </Markdown>

                    <CodeBlock
                        language="bash"
                        code={dedent`
                            npm install @posthog/ai @opentelemetry/api @opentelemetry/exporter-trace-otlp-http @vercel/otel
                        `}
                    />
                </>
            ),
        },
        {
            title: 'Set environment variables',
            badge: 'required',
            content: (
                <>
                    <Markdown>Set your PostHog project token and host in your Eve project's environment.</Markdown>

                    <CodeBlock
                        language="bash"
                        code={dedent`
                            POSTHOG_PROJECT_TOKEN=<ph_project_token>
                            POSTHOG_HOST=<ph_client_api_host>
                        `}
                    />
                </>
            ),
        },
        {
            title: 'Add Eve instrumentation',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Create `agent/instrumentation.ts`. Eve discovers this file and starts the exporter when your
                        agent server starts. The optional `events` handler identifies spans using the user who started
                        the session, falling back to the caller for the current turn.
                    </Markdown>

                    <CodeBlock
                        language="typescript"
                        code={dedent`
                            import { trace } from '@opentelemetry/api'
                            import { PostHogTraceExporter } from '@posthog/ai/otel'
                            import { registerOTel } from '@vercel/otel'
                            import { defineInstrumentation } from 'eve/instrumentation'

                            export default defineInstrumentation({
                              setup: ({ agentName }) =>
                                registerOTel({
                                  serviceName: agentName,
                                  traceExporter: new PostHogTraceExporter({
                                    projectToken: process.env.POSTHOG_PROJECT_TOKEN!,
                                    host: process.env.POSTHOG_HOST,
                                  }),
                                }),
                              // Optional: Link Eve and AI SDK spans to a PostHog user.
                              events: {
                                'step.started'(input) {
                                  const distinctId =
                                    input.session.auth.initiator?.principalId ??
                                    input.session.auth.current?.principalId

                                  if (!distinctId) {
                                    return undefined
                                  }

                                  trace.getActiveSpan()?.setAttribute('posthog.distinct_id', distinctId)
                                  return { runtimeContext: { posthog_distinct_id: distinctId } }
                                },
                              },
                            })
                        `}
                    />

                    <CalloutBox type="fyi" icon="IconInfo" title="How this works">
                        <Markdown>
                            Eve emits Vercel AI SDK OpenTelemetry spans. `PostHogTraceExporter` sends the AI spans to
                            PostHog's OTLP ingestion endpoint. PostHog keeps the trace hierarchy, identifies the
                            framework as Eve, and groups turns using `eve.session.id`.
                        </Markdown>
                    </CalloutBox>

                    <Blockquote>
                        <Markdown>
                            **Note:** To capture LLM events anonymously, omit the `events` handler. See our docs on
                            [anonymous vs identified
                            events](https://posthog.com/docs/data/anonymous-vs-identified-events) to learn more.
                        </Markdown>
                    </Blockquote>

                    <Blockquote>
                        <Markdown>
                            **Data capture:** Eve records full message history and model outputs by default. Set
                            `recordInputs: false` or `recordOutputs: false` in `defineInstrumentation` if you do not
                            want that data included in exported spans.
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

export const EveInstallation = createInstallation(getEveSteps)
