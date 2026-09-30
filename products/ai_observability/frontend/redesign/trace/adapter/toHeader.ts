import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { LLMTrace } from '~/queries/schema/schema-general'

import { sanitizeTraceUrlSearchParams } from '../../../utils'
import { TraceHeaderProps } from '../components/TraceHeader'
import { LabeledLink } from '../types'
import { hasTraceError } from './toTraceTree'

export interface TraceNeighbours {
    olderTraceId: string | null
    olderTimestamp: string | null
    newerTraceId: string | null
    newerTimestamp: string | null
}

type SearchParams = Record<string, unknown>

function neighbourHref(traceId: string | null, timestamp: string | null, searchParams: SearchParams): string | null {
    return traceId
        ? combineUrl(urls.aiObservabilityTrace(traceId), {
              ...sanitizeTraceUrlSearchParams(searchParams),
              timestamp: timestamp ?? undefined,
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

export function toHeader(trace: LLMTrace, neighbours: TraceNeighbours, searchParams: SearchParams): TraceHeaderProps {
    return {
        name: trace.traceName || 'Untitled trace',
        hasError: hasTraceError(trace),
        olderHref: neighbourHref(neighbours.olderTraceId, neighbours.olderTimestamp, searchParams),
        newerHref: neighbourHref(neighbours.newerTraceId, neighbours.newerTimestamp, searchParams),
        backLink: toBackLink(searchParams),
    }
}
