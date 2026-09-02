import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getEveSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { Blockquote, CodeBlock, Markdown, dedent, snippets } = ctx

    const NotableGenerationProperties = snippets?.NotableGenerationProperties

    return [
        {
            title: 'Install dependencies',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Install PostHog AI, its OpenTelemetry peer dependencies, and Vercel's OpenTelemetry package.
                    </Markdown>

                    <CodeBlock
                        language="bash"
                        code={dedent`
                            npm install @posthog/ai @opentelemetry/api @opentelemetry/exporter-trace-otlp-http @opentelemetry/sdk-trace-base @vercel/otel
                        `}
                    />

                    <Blockquote>
                        <Markdown>
                            **Version note:** This example uses `projectToken`, which is available in `@posthog/ai`
                            7.19.6 and later. Earlier 7.x versions use `apiKey`.
                        </Markdown>
                    </Blockquote>
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
                        agent server starts. The optional `events` handler uses [Eve runtime
                        context](https://eve.dev/docs/guides/instrumentation#runtime-context) to identify spans with the
                        user who started the session, falling back to the caller for the current turn.
                    </Markdown>

                    <CodeBlock
                        language="typescript"
                        code={dedent`
                            import { trace } from '@opentelemetry/api'
                            import { SimpleSpanProcessor } from '@opentelemetry/sdk-trace-base'
                            import { PostHogTraceExporter } from '@posthog/ai/otel'
                            import { registerOTel } from '@vercel/otel'
                            import { defineInstrumentation } from 'eve/instrumentation'

                            export default defineInstrumentation({
                              setup: ({ agentName }) =>
                                registerOTel({
                                  serviceName: agentName,
                                  spanProcessors: [
                                    new SimpleSpanProcessor(
                                      new PostHogTraceExporter({
                                        projectToken: process.env.POSTHOG_PROJECT_TOKEN!,
                                        host: process.env.POSTHOG_HOST,
                                      })
                                    ),
                                  ],
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

                    <Blockquote>
                        <Markdown>
                            **Note:** To capture LLM events anonymously, omit the `events` handler. See our docs on
                            [anonymous vs identified
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

export const EveInstallation = createInstallation(getEveSteps)
