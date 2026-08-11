import { combineUrl, router } from 'kea-router'

import { SSOProvider } from '~/types'

/**
 * Build the Django login URL for an SSO provider. Lives outside the React components so kea logics
 * can redirect to a provider without rendering a link.
 */
export function getSocialLoginUrl(
    provider: SSOProvider,
    extraQueryParams?: Record<string, string>,
    // Components pass their subscribed `searchParams` so the href stays reactive.
    searchParams: Record<string, any> = router.values.searchParams
): string {
    const loginParams: Record<string, string> = { ...extraQueryParams }
    const { next } = searchParams
    if (next) {
        loginParams.next = next
    }
    if (provider === 'saml') {
        // SAML-based login requires an extra param as technically we can support multiple SAML backends
        loginParams.idp = 'posthog_custom'
    }
    return combineUrl(`/login/${provider}/`, loginParams).url
}
