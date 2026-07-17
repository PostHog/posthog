import { useValues } from 'kea'
import { useMemo } from 'react'

import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { Region, SLACK_INTEGRATION_SCOPES, SLACK_INTEGRATION_SCOPES_IN_REVIEW } from '~/types'

/**
 * Required Slack OAuth scopes for the current PostHog instance.
 *
 * On the DEV instance and local dev the PostHog Slack app manifest lists the in-review
 * scopes, so we both request them at install and compare against them here. Anywhere
 * else (US / EU / self-hosted) Slack rejects them as ``invalid_scope`` so we stay on
 * the always-on list.
 *
 * Used by both the settings-side ``SlackIntegration`` connect/manage UI and the OAuth
 * landing page's status hook so the two surfaces always agree on what "fully scoped"
 * means.
 */
export function useSlackRequiredScopes(): string[] {
    const { preflight, isDev } = useValues(preflightLogic)
    return useMemo(
        () =>
            isDev || preflight?.region === Region.DEV
                ? [...SLACK_INTEGRATION_SCOPES, ...SLACK_INTEGRATION_SCOPES_IN_REVIEW]
                : [...SLACK_INTEGRATION_SCOPES],
        [isDev, preflight?.region]
    )
}
