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

/** One event for every screen of the login and signup flow, so a single funnel covers both. The
 * OAuth client is attached when the person arrived from a signed-out `/oauth/authorize`. */
export function captureAuthStepViewed(step: AuthStep, entry: AuthEntry | null): void {
    const connection = readPendingOAuthConnection()
    // pinned: analytics event name
    posthog.capture('auth step viewed', {
        step,
        entry,
        oauth_client_name: connection?.clientName,
        oauth_client_id: connection?.clientId,
    })
}
