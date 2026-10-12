// Maps raw OAuth error codes that providers return in the callback `?error=` param to messages a
// user can act on. Ad-platform sources (LinkedIn, Meta, Google Ads) route through the generic
// integration callback, so without this the user sees cryptic codes like `access_denied` or
// `user_connector_authorize` verbatim. Unknown codes fall back to the raw value so support can
// still identify them.
// Search param carrying the raw provider error code from the callback to whichever page the user
// lands on, so the explanation stays on screen instead of vanishing with a toast.
// pinned: URL search param — the callback redirect and the landing page both read it.
export const INTEGRATION_ERROR_PARAM = 'integration_error'

// Search param carrying the provider's `error_description`. Microsoft puts the sign-in error code
// (AADSTS…) only there, so without it neither the user nor support can see why sign-in failed.
// pinned: URL search param — the callback redirect and the landing page both read it.
export const INTEGRATION_ERROR_DESCRIPTION_PARAM = 'integration_error_description'

const MAX_PROVIDER_ERROR_DESCRIPTION_LENGTH = 300

// Not a provider code: PostHog's own CSRF state cookie outlived the authorization round-trip, so
// the callback can't be verified. It rides the same param as the provider codes to reach whichever
// page the user lands on.
// pinned: URL search param value — the callback redirect and the landing page both read it.
export const OAUTH_STATE_EXPIRED = 'posthog_state_expired'

const OAUTH_CALLBACK_ERROR_MESSAGES: Record<string, string> = {
    [OAUTH_STATE_EXPIRED]:
        'This connection attempt expired before it could finish. Start it again and approve access without waiting in between.',
    access_denied: 'Authorization was canceled. Please try connecting again and approve access to continue.',
    user_connector_authorize:
        'Authorization was not completed. Please try connecting again and approve access to continue.',
    invalid_scope:
        'The connection was missing required permissions. Please try connecting again and grant all requested access.',
    server_error: 'The provider had a problem completing the connection. Please try again in a moment.',
    temporarily_unavailable: 'The provider is temporarily unavailable. Please try again in a moment.',
}

// Slack answers `access_denied` for two different outcomes: someone declined the install, and a
// workspace with app approval turned on filing a pending request for an admin to review. The
// generic copy above claims the first and tells the user to approve access, which they cannot do.
const OAUTH_CALLBACK_ERROR_MESSAGES_BY_KIND: Record<string, Record<string, string>> = {
    slack: {
        access_denied:
            'PostHog was not added to your Slack workspace. Either the install was declined, or your workspace requires an admin to approve new apps and the request is now waiting for one. Once an admin approves it, come back to this page and click "Add to Slack" again.',
    },
    // Microsoft rejects some accounts at the authorize step, before PostHog sees a code. The cause
    // is in the user's Microsoft account or tenant, so a retry in another browser does not help.
    'bing-ads': {
        invalid_client:
            "Microsoft didn't let this account sign in to PostHog. Check that you use the Microsoft account that has access to your Microsoft Advertising account. If you use a work account, your organization may block third-party apps, so ask your Microsoft admin to allow PostHog.",
    },
}

/** Keeps the first line of a provider's `error_description`. Microsoft appends trace and
 *  correlation IDs on later lines, which support does not need in the message. */
export function summarizeProviderErrorDescription(description: unknown): string | undefined {
    if (typeof description !== 'string') {
        return undefined
    }
    const firstLine = description.trim().split(/\r?\n/)[0].trim()
    if (!firstLine) {
        return undefined
    }
    return firstLine.length > MAX_PROVIDER_ERROR_DESCRIPTION_LENGTH
        ? `${firstLine.slice(0, MAX_PROVIDER_ERROR_DESCRIPTION_LENGTH)}…`
        : firstLine
}

export function describeOAuthCallbackError(error: string, kind?: string, description?: unknown): string {
    const kindSpecific = kind ? OAUTH_CALLBACK_ERROR_MESSAGES_BY_KIND[kind]?.[error] : undefined
    const message = kindSpecific ?? OAUTH_CALLBACK_ERROR_MESSAGES[error] ?? `Failed due to "${error}".`
    const summary = summarizeProviderErrorDescription(description)
    return summary ? `${message} Details from the provider: ${summary}` : message
}
