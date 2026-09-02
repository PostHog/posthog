import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

export interface FeatureRequestDetailUrlOptions {
    requestId: string
    origin?: string
    searchParams?: Record<string, unknown>
}

export function getFeatureRequestDetailUrl({
    requestId,
    origin,
    searchParams = {},
}: FeatureRequestDetailUrlOptions): string {
    return combineUrl(urls.customerAnalyticsFeatureRequests(requestId), {
        ...searchParams,
        ...(origin ? { origin } : {}),
    }).url
}

function isInternalOrigin(origin: unknown): origin is string {
    if (typeof origin !== 'string' || !origin.startsWith('/')) {
        return false
    }
    try {
        return new URL(origin, 'https://posthog.local').origin === 'https://posthog.local'
    } catch {
        return false
    }
}

export function getFeatureRequestBackUrl(origin: unknown, listSearchParams: Record<string, string>): string {
    return isInternalOrigin(origin) ? origin : combineUrl(urls.customerAnalyticsFeatureRequests(), listSearchParams).url
}

export function getFeatureRequestBackLabel(origin: unknown): string | null {
    return isInternalOrigin(origin) ? null : 'Feature requests'
}
