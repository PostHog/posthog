import { ApiError } from 'lib/api'

import type { BillingAlertDestinationSummaryApi } from './generated/api.schemas'

export function offsetFromPageLink(link: string | null | undefined, fallback = 0): number {
    if (!link) {
        return fallback
    }
    try {
        const offset = Number(new URL(link, 'https://app.posthog.com').searchParams.get('offset'))
        return Number.isSafeInteger(offset) && offset >= 0 ? offset : fallback
    } catch {
        return fallback
    }
}

export function billingAlertRequestError(error: unknown, fallback = 'Request failed.'): string {
    if (error instanceof ApiError) {
        return error.detail || fallback
    }
    return error instanceof Error ? error.message : fallback
}

/** Identity of a destination group, shared by delete-in-flight tracking and list rendering. */
export function destinationKey(
    destination: Pick<BillingAlertDestinationSummaryApi, 'type' | 'hog_function_ids'>
): string {
    return `${destination.type}-${destination.hog_function_ids.join('-')}`
}
