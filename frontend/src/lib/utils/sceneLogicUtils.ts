import { Params } from 'scenes/sceneTypes'

/**
 * Forwards whitelisted query parameters from the current URL to the redirect URL.
 * Only forwards params that exist in the current URL and don't already exist in the redirect URL.
 * This is specifically used for scene redirects to maintain important query parameters across redirects.
 */
export function withForwardedSearchParams(
    redirectUrl: string,
    currentSearchParams: Params,
    forwardedQueryParams: string[]
): string {
    // If no params to forward, return the original URL
    if (!forwardedQueryParams?.length) {
        return redirectUrl
    }

    const redirectUrlObj = new URL(redirectUrl, window.location.origin)
    const redirectSearchParams = new URLSearchParams(redirectUrlObj.search)
    let paramsWereForwarded = false

    // For each whitelisted param that exists in current URL
    forwardedQueryParams.forEach((param) => {
        if (currentSearchParams[param] !== undefined && !redirectSearchParams.has(param)) {
            redirectSearchParams.set(param, currentSearchParams[param])
            paramsWereForwarded = true
        }
    })

    // Only modify the URL if we actually forwarded any params
    if (!paramsWereForwarded) {
        return redirectUrl
    }

    // Reconstruct the URL with the forwarded params
    redirectUrlObj.search = redirectSearchParams.toString()
    // Return just the pathname and search to avoid origin being included
    return redirectUrlObj.pathname + redirectUrlObj.search + redirectUrlObj.hash
}
