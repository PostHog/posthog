import { SLACK_INTEGRATION_OPTIONAL_SCOPES, SLACK_INTEGRATION_SCOPES } from '~/types'

/**
 * Required Slack OAuth scopes for the current PostHog instance.
 *
 * Every scope PostHog requests is approved for the public app, so this is the same list
 * on every instance. If a future scope has to wait on Slack review, this is where the
 * DEV-only union goes back — see the note by ``SlackIntegrationScope`` in ``~/types``.
 *
 * Scopes the manifest marks optional are left out: an install that declines one still works,
 * so flagging it would send people back to Slack for nothing.
 *
 * Used by both the settings-side ``SlackIntegration`` connect/manage UI and the OAuth
 * landing page's status hook so the two surfaces always agree on what "fully scoped"
 * means.
 */
export function useSlackRequiredScopes(): string[] {
    const optional = new Set<string>(SLACK_INTEGRATION_OPTIONAL_SCOPES)
    return SLACK_INTEGRATION_SCOPES.filter((scope) => !optional.has(scope))
}
