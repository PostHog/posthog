import { useValues } from 'kea'

import { requestsSlackInReviewScopes } from 'lib/integrations/integrationScopes'
import { preflightLogic } from 'lib/logic/preflightLogic'

import { slackRequestedScopes } from '~/types'

/**
 * Required Slack OAuth scopes for the current PostHog instance.
 *
 * The DEV instance and local development also require the scopes that wait on Slack review,
 * because they request them at install. See the note by ``SlackIntegrationScopeInReview`` in ``~/types``.
 *
 * Used by both the settings-side ``SlackIntegration`` connect/manage UI and the OAuth
 * landing page's status hook so the two surfaces always agree on what "fully scoped"
 * means.
 */
export function useSlackRequiredScopes(): string[] {
    const { preflight } = useValues(preflightLogic)
    return slackRequestedScopes(requestsSlackInReviewScopes(preflight))
}
