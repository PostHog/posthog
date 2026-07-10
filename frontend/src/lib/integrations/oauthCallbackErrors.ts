// Maps raw OAuth error codes that providers return in the callback `?error=` param to messages a
// user can act on. Ad-platform sources (LinkedIn, Meta, Google Ads) route through the generic
// integration callback, so without this the user sees cryptic codes like `access_denied` or
// `user_connector_authorize` verbatim. Unknown codes fall back to the raw value so support can
// still identify them.
const OAUTH_CALLBACK_ERROR_MESSAGES: Record<string, string> = {
    access_denied: 'Authorization was canceled. Please try connecting again and approve access to continue.',
    user_connector_authorize:
        'Authorization was not completed. Please try connecting again and approve access to continue.',
    invalid_scope:
        'The connection was missing required permissions. Please try connecting again and grant all requested access.',
    server_error: 'The provider had a problem completing the connection. Please try again in a moment.',
    temporarily_unavailable: 'The provider is temporarily unavailable. Please try again in a moment.',
}

export function describeOAuthCallbackError(error: string): string {
    return OAUTH_CALLBACK_ERROR_MESSAGES[error] ?? `Failed due to "${error}"`
}
