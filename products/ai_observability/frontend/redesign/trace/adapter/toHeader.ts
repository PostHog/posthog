import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import type { TraceNeighbourApi, TraceNeighboursApi } from '../../../generated/api.schemas'
import { sanitizeTraceUrlSearchParams } from '../../../utils'
import { TraceHeaderProps } from '../components/TraceHeader'
import { LabeledLink } from '../types'

type SearchParams = Record<string, unknown>

function neighbourHref(neighbour: TraceNeighbourApi | null | undefined, searchParams: SearchParams): string | null {
    return neighbour
        ? combineUrl(urls.aiObservabilityTrace(neighbour.id), {
              ...sanitizeTraceUrlSearchParams(searchParams),
              timestamp: neighbour.createdAt,
          }).url
        : null
}

// Matches the legacy scene: a link opened from a review queue returns to that queue, other links to the reviews tab.
function reviewsBackHref(searchParams: SearchParams): string {
    const inQueue = typeof searchParams.queue_id === 'string' && searchParams.queue_id !== ''
    return combineUrl(urls.aiObservabilityReviews(), {
        ...sanitizeTraceUrlSearchParams(searchParams),
        human_reviews_tab: inQueue ? undefined : 'reviews',
    }).url
}

export function toBackLink(searchParams: SearchParams): LabeledLink {
    if (searchParams.back_to === 'reviews') {
        return { label: 'Back to reviews', href: reviewsBackHref(searchParams) }
    }
    const listParams = sanitizeTraceUrlSearchParams(searchParams)
    if (searchParams.back_to === 'generations') {
        return {
            label: 'Back to generations',
            href: combineUrl(urls.aiObservabilityGenerations(), listParams).url,
        }
    }
    return { label: 'Back to traces', href: combineUrl(urls.aiObservabilityTraces(), listParams).url }
}

export function toHeader(
    title: { name: string; hasError: boolean },
    neighbours: TraceNeighboursApi | null,
    searchParams: SearchParams
): TraceHeaderProps {
    return {
        name: title.name,
        hasError: title.hasError,
        olderHref: neighbourHref(neighbours?.older, searchParams),
        newerHref: neighbourHref(neighbours?.newer, searchParams),
        backLink: toBackLink(searchParams),
    }
}
