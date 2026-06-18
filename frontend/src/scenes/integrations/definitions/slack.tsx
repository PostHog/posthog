import { getMissingScopes, IntegrationScopesWarning } from 'lib/integrations/IntegrationScopesWarning'
import { ICONS } from 'lib/integrations/utils'

import { IntegrationType } from '~/types'

import { SlackIntegration } from '../components/SlackIntegration'
import { useSlackRequiredScopes } from '../components/slackScopes'
import { defineIntegration } from '../integrationDefinition'
import { IntegrationStatus } from '../integrationTypes'

// Render the scopes-mismatch banner directly under the OAuth success card so an install with
// the wrong scope set surfaces it while the user is still in the install flow, instead of
// hiding it behind a separate trip to Settings → Integrations that they have no reason to take.
function SlackPostConnect({ integration }: { integration: IntegrationType }): JSX.Element {
    const requiredScopes = useSlackRequiredScopes()
    return <IntegrationScopesWarning integration={integration} schema={{ requiredScopes: requiredScopes.join(' ') }} />
}

// Aggregate status feeding the landing page headline: any install missing required scopes
// drops the whole page into the "needs attention" state. ``getMissingScopes`` returns []
// for legacy rows that have no scopes recorded — same fail-open behavior as the banner.
function useSlackStatus(integrations: IntegrationType[]): IntegrationStatus {
    const requiredScopes = useSlackRequiredScopes()
    const anyNeedsAttention = integrations.some(
        (integration) => getMissingScopes(integration, requiredScopes).length > 0
    )
    return anyNeedsAttention ? 'needs_attention' : 'ok'
}

export const Slack = defineIntegration(
    {
        slug: 'slack',
        kind: 'slack',
        name: 'Slack',
        logo: ICONS.slack,
        banner: 'https://res.cloudinary.com/dmukukwp6/image/upload/slack_app_update_docs_f0c917f70a',
        subtitle: 'Bring PostHog into Slack — from scheduled reports to an AI agent that ships code',
        description:
            'Tag @PostHog in any Slack thread to draft pull requests, ship code changes, ask data questions, and run SQL — all without leaving Slack. You also get insights, dashboards, and alerts delivered straight to your channels.',
        capabilities: [
            'Tag @PostHog in a thread to draft pull requests and ship code changes',
            'Tag @PostHog to ask data questions and run SQL',
            'Subscribe to insights and dashboards for scheduled reports',
            'Receive alerts and error-tracking notifications in your channels',
            'Manage feature flags, experiments, and surveys from Slack',
        ],
        docsUrl: 'https://posthog.com/docs/webhooks/slack',
        PostConnect: SlackPostConnect,
        useStatus: useSlackStatus,
    },
    SlackIntegration
)
