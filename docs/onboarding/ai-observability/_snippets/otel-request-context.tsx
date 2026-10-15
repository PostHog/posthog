import { OnboardingComponentsContext } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../../steps'

export interface OtelRequestContextConfig {
    /** Language tabs the surrounding page shows, in the order it shows them. */
    languages: ('Python' | 'Node' | 'Go')[]
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

const NODE_CODE = `
// Requires @posthog/ai 8.14.0 and posthog-node 5.15.0 or later
import { PostHog } from 'posthog-node'

const posthog = new PostHog('<ph_project_token>', { host: '<ph_client_api_host>' })

// Pass the client to the processor you configured earlier
new PostHogSpanProcessor({
  projectToken: '<ph_project_token>',
  host: '<ph_client_api_host>',
  client: posthog,
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

const CODE_BY_LANGUAGE = {
    Python: { language: 'python', file: 'Python', code: PYTHON_CODE },
    Node: { language: 'typescript', file: 'Node', code: NODE_CODE },
    Go: { language: 'go', file: 'Go', code: GO_CODE },
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

                <CodeBlock blocks={config.languages.map((language) => CODE_BY_LANGUAGE[language])} />

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
                            from the \`X-PostHog-Distinct-Id\` and \`X-PostHog-Session-Id\` headers.
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
