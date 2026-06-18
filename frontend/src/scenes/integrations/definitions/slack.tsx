import { useValues } from 'kea'
import { useMemo } from 'react'

import { IntegrationScopesWarning } from 'lib/integrations/IntegrationScopesWarning'
import { ICONS } from 'lib/integrations/utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { IntegrationType, Region, SLACK_INTEGRATION_SCOPES, SLACK_INTEGRATION_SCOPES_IN_REVIEW } from '~/types'

import { SlackIntegration } from '../components/SlackIntegration'
import { defineIntegration } from '../integrationDefinition'
import { IntegrationStatus } from '../integrationTypes'

// Required-scope construction mirrors ``SlackIntegration``'s settings-side computation: on the
// DEV instance and local dev the PostHog Slack app manifest lists extra in-review scopes, so
// we both request them at install and compare against them. Anywhere else they'd be rejected
// by Slack as ``invalid_scope`` and would falsely flag the install as broken.
function useSlackRequiredScopes(): string[] {
    const { preflight, isDev } = useValues(preflightLogic)
    return useMemo(
        () =>
            isDev || preflight?.region === Region.DEV
                ? [...SLACK_INTEGRATION_SCOPES, ...SLACK_INTEGRATION_SCOPES_IN_REVIEW]
                : [...SLACK_INTEGRATION_SCOPES],
        [isDev, preflight?.region]
    )
}

function parseGrantedScopes(integration: IntegrationType): string[] {
    // Slack returns the scopes as a comma-separated string under ``config.scope``. The
    // settings-side ``IntegrationScopesWarning`` is more permissive (also checks ``scopes``
    // and accepts arrays) for cross-integration reuse; here we match Slack's actual shape.
    const raw = integration.config?.scope
    if (typeof raw !== 'string') {
        return []
    }
    return raw
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)
}

// Render the scopes-mismatch banner directly under the OAuth success card so an install with
// the wrong scope set surfaces it while the user is still in the install flow, instead of
// hiding it behind a separate trip to Settings → Integrations that they have no reason to take.
function SlackPostConnect({ integration }: { integration: IntegrationType }): JSX.Element {
    const requiredScopes = useSlackRequiredScopes()
    return <IntegrationScopesWarning integration={integration} schema={{ requiredScopes: requiredScopes.join(' ') }} />
}

// Aggregate status feeding the landing page headline: any install missing required scopes
// drops the whole page into the "needs attention" state. We don't flag an install with no
// scopes recorded at all — that's typically a legacy row predating the scope field, and
// ``IntegrationScopesWarning`` already declines to render in that case.
function useSlackStatus(integrations: IntegrationType[]): IntegrationStatus {
    const requiredScopes = useSlackRequiredScopes()
    const anyNeedsAttention = integrations.some((integration) => {
        const granted = parseGrantedScopes(integration)
        if (granted.length === 0) {
            return false
        }
        return requiredScopes.some((scope) => !granted.includes(scope))
    })
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
