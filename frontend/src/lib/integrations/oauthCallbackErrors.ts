// Maps raw OAuth error codes that providers return in the callback `?error=` param to messages a
// user can act on. Ad-platform sources (LinkedIn, Meta, Google Ads) route through the generic
// integration callback, so without this the user sees cryptic codes like `access_denied` or
// `user_connector_authorize` verbatim. Unknown codes fall back to the raw value so support can
// still identify them.
// Search param carrying the raw provider error code from the callback to whichever page the user
// lands on, so the explanation stays on screen instead of vanishing with a toast.
// pinned: URL search param — the callback redirect and the landing page both read it.
export const INTEGRATION_ERROR_PARAM = 'integration_error'

const OAUTH_CALLBACK_ERROR_MESSAGES: Record<string, string> = {
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
}

export function describeOAuthCallbackError(error: string, kind?: string): string {
    const kindSpecific = kind ? OAUTH_CALLBACK_ERROR_MESSAGES_BY_KIND[kind]?.[error] : undefined
    return kindSpecific ?? OAUTH_CALLBACK_ERROR_MESSAGES[error] ?? `Failed due to "${error}"`
}
