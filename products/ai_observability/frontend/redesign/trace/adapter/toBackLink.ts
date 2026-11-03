import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { sanitizeTraceUrlSearchParams } from '../../../utils'
import { LabeledLink } from '../types'

type SearchParams = Record<string, unknown>

// The lists read `search` as their own search term.
function listParams(searchParams: SearchParams): SearchParams {
    return sanitizeTraceUrlSearchParams(searchParams, { removeSearch: true })
}

export function toFullPageListParams(searchParams: SearchParams): SearchParams {
    const { trace: _trace, ts: _ts, step: _step, ...params } = listParams(searchParams)
    return params
}

// Matches the legacy scene: a link opened from a review queue returns to that queue, other links to the reviews tab.
function reviewsBackHref(searchParams: SearchParams): string {
    const inQueue = typeof searchParams.queue_id === 'string' && searchParams.queue_id !== ''
    return combineUrl(urls.aiObservabilityReviews(), {
        ...listParams(searchParams),
        human_reviews_tab: inQueue ? undefined : 'reviews',
    }).url
}

export function toBackLink(searchParams: SearchParams): LabeledLink {
    if (searchParams.back_to === 'reviews') {
        return { label: 'Back to reviews', href: reviewsBackHref(searchParams) }
    }
    if (searchParams.back_to === 'generations') {
        return {
            label: 'Back to generations',
            href: combineUrl(urls.aiObservabilityGenerations(), listParams(searchParams)).url,
        }
    }
    return { label: 'Back to traces', href: combineUrl(urls.aiObservabilityTraces(), listParams(searchParams)).url }
}
