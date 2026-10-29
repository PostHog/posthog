import { OnboardingComponentsContext } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../../steps'

export interface OtelRequestContextConfig {
    /** Language tabs the surrounding page shows, in the order it shows them. */
    languages: ('Python' | 'Node' | 'Go')[]
    /** The tracer setup class the page's Node setup step uses. Defaults to `NodeSDK`. */
    nodeTracerSetup?: 'NodeSDK' | 'NodeTracerProvider'
}

const PYTHON_CODE = `
# Requires posthog 7.70.0 or later
import posthog

with posthog.new_context():
    posthog.identify_context(user_id)
    posthog.tag("$ai_session_id", conversation_id)
    posthog.tag("plan", "pro")  # custom properties work too

    reply = handle_turn(user_message)
`.trim()

const NODE_SETUP_VARIABLES = { NodeSDK: 'sdk', NodeTracerProvider: 'provider' }

const getNodeCode = (tracerSetup: 'NodeSDK' | 'NodeTracerProvider'): string =>
    `
// Requires @posthog/ai 8.14.0 and posthog-node 5.15.0 or later
import { PostHog } from 'posthog-node'

const posthog = new PostHog('<ph_project_token>', { host: '<ph_client_api_host>' })

const ${NODE_SETUP_VARIABLES[tracerSetup]} = new ${tracerSetup}({
  // ...the rest of your setup from the earlier step
  spanProcessors: [
    new PostHogSpanProcessor({
      projectToken: '<ph_project_token>',
      host: '<ph_client_api_host>',
      client: posthog,
    }),
  ],
})

const reply = await posthog.withContext(
  {
    distinctId: userId,
    properties: {
      $ai_session_id: conversationId,
      plan: 'pro', // custom properties work too
    },
  },
  () => handleTurn(userMessage)
)
`.trim()

const GO_CODE = `
// Requires github.com/posthog/posthog-go/otel v1.35.0 or later
import "github.com/posthog/posthog-go"

ctx = posthog.WithRequestContext(ctx, posthog.RequestContext{
    DistinctId: userID,
    Properties: posthog.Properties{
        "$ai_session_id": conversationID,
        "plan":           "pro", // custom properties work too
    },
})

reply := handleTurn(ctx, userMessage)
`.trim()

const getCodeBlock = (
    language: OtelRequestContextConfig['languages'][number],
    config: OtelRequestContextConfig
): { language: string; file: string; code: string } => {
    switch (language) {
        case 'Python':
            return { language: 'python', file: 'Python', code: PYTHON_CODE }
        case 'Node':
            return { language: 'typescript', file: 'Node', code: getNodeCode(config.nodeTracerSetup ?? 'NodeSDK') }
        case 'Go':
            return { language: 'go', file: 'Go', code: GO_CODE }
    }
}

export const getOtelRequestContextStep = (
    ctx: OnboardingComponentsContext,
    config: OtelRequestContextConfig
): StepDefinition => {
    const { CodeBlock, Markdown, dedent } = ctx

    return {
        title: 'Users and sessions',
        badge: 'recommended',
        content: (
            <>
                <Markdown>
                    {dedent`
                        A server usually handles requests for many users, so a resource attribute can't say who
                        each trace belongs to. Wrap each request in a PostHog context instead. The PostHog span
                        processor adds the context's distinct ID and properties to every AI span started inside it.
                        Other span processors and exporters on the same provider don't see them.

                        Set \`$ai_session_id\` if your product has multi-turn conversations, so the Sessions tab can
                        group their traces. Workloads that finish in a single trace, like batch jobs or one-shot
                        generation, don't need it.
                    `}
                </Markdown>

                <CodeBlock blocks={config.languages.map((language) => getCodeBlock(language, config))} />

                {config.languages.includes('Node') && (
                    <Markdown>
                        {dedent`
                            On Node, install \`posthog-node\` and pass the client as the \`client\` option of your
                            \`PostHogSpanProcessor\`. Without it, the processor doesn't read the context.
                        `}
                    </Markdown>
                )}

                {config.languages.includes('Go') && (
                    <Markdown>
                        {dedent`
                            In Go, \`posthog.NewRequestContextMiddleware\` fills the context for each HTTP request
                            from the \`X-PostHog-Distinct-Id\` and \`X-PostHog-Session-Id\` headers. The session
                            header sets the web session ID (\`$session_id\`), not \`$ai_session_id\`, so set
                            \`$ai_session_id\` in \`Properties\` to group traces in the Sessions tab.
                        `}
                    </Markdown>
                )}

                <Markdown>
                    {dedent`
                        A distinct ID set this way takes priority over a \`posthog.distinct_id\` resource attribute,
                        so you can keep the resource attribute as the fallback for work outside a request. If your
                        instrumentation already sets the \`gen_ai.conversation.id\` attribute, PostHog uses it as
                        the session ID, and an explicit \`$ai_session_id\` takes priority over it.
                    `}
                </Markdown>
            </>
        ),
    }
}
