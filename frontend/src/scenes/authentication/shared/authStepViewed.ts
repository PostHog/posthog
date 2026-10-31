import posthog from 'posthog-js'

import { readPendingOAuthConnection } from './pendingOAuthConnectionLogic'

/** The URL a person opened the auth page on. Both URLs render the same page with different copy.
 * pinned: analytics property value on `auth step viewed` and `auth email submitted` */
export type AuthEntry = 'login' | 'signup'

/** pinned: analytics property value on `auth step viewed` */
export type AuthStep =
    | 'email'
    | 'login'
    | 'login_code'
    | 'signup_credentials'
    | 'signup_profile'
    | 'signup_pending_invite'
    | 'verify_email'

/** The OAuth client a signed-out `/oauth/authorize` sent the person from, for every auth event.
 * pinned: analytics property names */
export function pendingOAuthConnectionProperties(): { oauth_client_name?: string; oauth_client_id?: string } {
    const connection = readPendingOAuthConnection()
    return { oauth_client_name: connection?.clientName, oauth_client_id: connection?.clientId }
}

export function captureAuthStepViewed(step: AuthStep, entry: AuthEntry | null): void {
    // pinned: analytics event name
    posthog.capture('auth step viewed', { step, entry, ...pendingOAuthConnectionProperties() })
}
