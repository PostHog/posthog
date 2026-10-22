import { useValues } from 'kea'
import { useMemo } from 'react'

import { requestedScopesForKind } from 'lib/integrations/integrationScopes'
import { preflightLogic } from 'lib/logic/preflightLogic'

/**
 * Required Slack OAuth scopes for the current PostHog instance.
 *
 * Preflight reports the backend's OAuth scopes so debug UI modes cannot accidentally
 * add permissions the Slack app does not request.
 *
 * Used by both the settings-side ``SlackIntegration`` connect/manage UI and the OAuth
 * landing page's status hook so the two surfaces always agree on what "fully scoped"
 * means.
 */
export function useSlackRequiredScopes(): string[] {
    const { preflight } = useValues(preflightLogic)
    return useMemo(() => requestedScopesForKind('slack', preflight), [preflight])
}
