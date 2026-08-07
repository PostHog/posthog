import { SLACK_INTEGRATION_SCOPES } from '~/types'

/**
 * Required Slack OAuth scopes for the current PostHog instance.
 *
 * Every scope PostHog requests is approved for the public app, so this is the same list
 * on every instance. If a future scope has to wait on Slack review, this is where the
 * DEV-only union goes back — see the note by ``SlackIntegrationScope`` in ``~/types``.
 *
 * Used by both the settings-side ``SlackIntegration`` connect/manage UI and the OAuth
 * landing page's status hook so the two surfaces always agree on what "fully scoped"
 * means.
 */
export function useSlackRequiredScopes(): string[] {
    return [...SLACK_INTEGRATION_SCOPES]
}
