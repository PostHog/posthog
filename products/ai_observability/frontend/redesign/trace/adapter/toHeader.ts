import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { sanitizeTraceUrlSearchParams } from '../../../utils'
import { TraceHeaderProps } from '../components/TraceHeader'
import { LabeledLink } from '../types'

export interface TraceNeighbours {
    olderTraceId: string | null
    olderTimestamp: string | null
    newerTraceId: string | null
    newerTimestamp: string | null
}

type SearchParams = Record<string, unknown>

// The lists read `search` as their own search term, and another trace starts with an empty search.
function listParams(searchParams: SearchParams): SearchParams {
    return sanitizeTraceUrlSearchParams(searchParams, { removeSearch: true })
}

function neighbourHref(traceId: string | null, timestamp: string | null, searchParams: SearchParams): string | null {
    return traceId
        ? combineUrl(urls.aiObservabilityTrace(traceId), {
              ...listParams(searchParams),
              timestamp: timestamp ?? undefined,
          }).url
        : null
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

export function toHeader(
    title: { name: string; hasError: boolean },
    neighbours: TraceNeighbours,
    searchParams: SearchParams
): TraceHeaderProps {
    return {
        name: title.name,
        hasError: title.hasError,
        olderHref: neighbourHref(neighbours.olderTraceId, neighbours.olderTimestamp, searchParams),
        newerHref: neighbourHref(neighbours.newerTraceId, neighbours.newerTimestamp, searchParams),
        backLink: toBackLink(searchParams),
    }
}
