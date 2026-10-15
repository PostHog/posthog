export interface ExternalAccountRoute {
    externalId: string
    tab?: string
}

export const EXTERNAL_ACCOUNT_ROUTE_PATTERN = '/customer_analytics/accounts/by-external-id/*'

export function isExternalAccountPath(pathname: string): boolean {
    return pathname.includes('/customer_analytics/accounts/by-external-id/')
}

export function shouldRenderLegacyCustomerAnalyticsScene(pathname: string, accountSceneEnabled: boolean): boolean {
    return !accountSceneEnabled && !isExternalAccountPath(pathname)
}

// kea-router decodes route captures before passing them to scenes. Read the raw pathname so an
// encoded literal percent sequence is decoded once, while encoded slashes remain one identity segment.
export function parseExternalAccountPath(pathname: string): ExternalAccountRoute | null {
    const match = pathname.match(/\/customer_analytics\/accounts\/by-external-id\/([^/]+)(?:\/([^/]+))?\/?$/)
    if (!match) {
        return null
    }

    try {
        const externalId = decodeURIComponent(match[1])
        const tab = match[2] ? decodeURIComponent(match[2]) : undefined
        return externalId ? { externalId, tab } : null
    } catch {
        return null
    }
}
