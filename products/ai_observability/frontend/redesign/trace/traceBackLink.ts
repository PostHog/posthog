import { combineUrl } from 'kea-router'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { sanitizeTraceUrlSearchParams } from '../../utils'
import { traceDrawerBackLabel } from './traceDrawerLists'
import { withoutTraceDrawerParams } from './traceDrawerRows'
import { LabeledLink } from './types'

type SearchParams = Record<string, unknown>

// A second `/`, a backslash, or a tab or newline that browsers drop from a URL would leave the site.
const INTERNAL_PATH = /^\/(?!\/)[^\\\s]*$/
const BACK_URL_PATH_PREFIXES = ['/ai-observability/', '/ai-evals/', '/prompt-management/']

// The lists read `search` as their own search term.
function listParams(searchParams: SearchParams): SearchParams {
    return sanitizeTraceUrlSearchParams(searchParams, { removeSearch: true })
}

export function toFullPageListParams(searchParams: SearchParams): SearchParams {
    return withoutTraceDrawerParams(listParams(searchParams))
}

// Matches the legacy scene: a link opened from a review queue returns to that queue, other links to the reviews tab.
function reviewsBackHref(searchParams: SearchParams): string {
    const inQueue = typeof searchParams.queue_id === 'string' && searchParams.queue_id !== ''
    return combineUrl(urls.aiObservabilityReviews(), {
        ...listParams(searchParams),
        human_reviews_tab: inQueue ? undefined : 'reviews',
    }).url
}

// An API path reaches the browser as a download, and an integration's authorize URL redirects off the site. The check
// reads the resolved path, because `/x/../api/` reaches the same URL.
function isInternalPath(url: unknown): url is string {
    if (typeof url !== 'string' || !INTERNAL_PATH.test(url)) {
        return false
    }
    const path = removeProjectIdIfPresent(new URL(url, window.location.origin).pathname)
    return BACK_URL_PATH_PREFIXES.some((prefix) => path.startsWith(prefix))
}

export function toBackLink(searchParams: SearchParams): LabeledLink {
    const { back_to: backTo, back_url: backUrl } = searchParams
    if (isInternalPath(backUrl)) {
        return { label: traceDrawerBackLabel(backTo), href: backUrl }
    }
    if (backTo === 'reviews') {
        return { label: traceDrawerBackLabel(backTo), href: reviewsBackHref(searchParams) }
    }
    if (backTo === 'generations') {
        return {
            label: traceDrawerBackLabel(backTo),
            href: combineUrl(urls.aiObservabilityGenerations(), listParams(searchParams)).url,
        }
    }
    return {
        label: traceDrawerBackLabel('traces'),
        href: combineUrl(urls.aiObservabilityTraces(), listParams(searchParams)).url,
    }
}
