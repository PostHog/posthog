import { actions, afterMount, isBreakpoint, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import { Sorting } from 'lib/lemon-ui/LemonTable'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { objectsEqual } from 'lib/utils/objects'
import { pluralize } from 'lib/utils/strings'

import { CountedPaginatedResponse } from '~/lib/api'
import { ApiConfig } from '~/lib/api'
import { PaginationManual } from '~/lib/lemon-ui/PaginationControl'
import { trackedActionToUrl } from '~/lib/logic/scenes/trackedActionToUrl'
import { urls } from '~/scenes/urls'

import { llmAnalyticsScoreDefinitionsList as aiObservabilityScoreDefinitionsList } from '../generated/api'
import type { ScoreDefinitionApi } from '../generated/api.schemas'
import type { aiObservabilityReviewsLogicType } from './aiObservabilityReviewsLogicType'
import { buildTraceReviewsListUrl, traceReviewListParamsFromFilters, traceReviewsApi } from './traceReviewsApi'
import { fetchAllReviewsForExport, formatReviewsForClipboard, type ReviewClipboardFormat } from './traceReviewsExport'
import type { TraceReview } from './types'

export const TRACE_REVIEWS_PER_PAGE = 30

export interface TraceReviewFilters {
    page: number
    search: string
    definition_id: string
    order_by: string
}

const ALLOWED_ORDER_BY_VALUES = new Set(['updated_at', '-updated_at', 'created_at', '-created_at'])

function cleanFilters(values: Record<string, unknown>): TraceReviewFilters {
    const orderByValue = values.order_by
    const orderBy =
        typeof orderByValue === 'string' && ALLOWED_ORDER_BY_VALUES.has(orderByValue) ? orderByValue : '-updated_at'

    return {
        page: parseInt(String(values.page)) || 1,
        search: String(values.search || ''),
        definition_id: typeof values.definition_id === 'string' ? values.definition_id : '',
        order_by: orderBy,
    }
}

// Only read the namespaced review_* params. The bare names (`search`, `page`,
// `order_by`) on this shared URL belong to the Scorers sub-tab, so reading them
// would leak Scorers state into the Reviews filters — e.g. clearing a review
// filter back to its default would resurrect a stale Scorers value on the next
// urlToAction pass. Matches the queues logic.
function filtersFromUrl(searchParams: Record<string, unknown>): TraceReviewFilters {
    return cleanFilters({
        page: searchParams.review_page,
        search: searchParams.review_search,
        definition_id: searchParams.review_definition_id,
        order_by: searchParams.review_order_by,
    })
}

function getUrlFilters(filters: TraceReviewFilters): Record<string, unknown> {
    return {
        review_page: filters.page === 1 ? undefined : filters.page,
        review_search: filters.search || undefined,
        review_definition_id: filters.definition_id || undefined,
        review_order_by: filters.order_by === '-updated_at' ? undefined : filters.order_by,
    }
}

export type AIObservabilityReviewsLogicProps = Record<string, never>

export const aiObservabilityReviewsLogic = kea<aiObservabilityReviewsLogicType>([
    path(['products', 'ai_observability', 'frontend', 'traceReviews', 'aiObservabilityReviewsLogic']),
    props({} as AIObservabilityReviewsLogicProps),

    actions({
        setFilters: (filters: Partial<TraceReviewFilters>, merge: boolean = true, debounce: boolean = true) => ({
            filters,
            merge,
            debounce,
        }),
        loadReviews: (debounce: boolean = true) => ({ debounce }),
        loadScoreDefinitionOptions: true,
        copyReviewsToClipboard: (format: ReviewClipboardFormat) => ({ format }),
    }),

    reducers({
        rawFilters: [
            null as Partial<TraceReviewFilters> | null,
            {
                setFilters: (state, { filters, merge }) =>
                    cleanFilters({
                        ...(merge ? state || {} : {}),
                        ...filters,
                        ...('page' in filters ? {} : { page: 1 }),
                    }),
            },
        ],
    }),

    loaders(({ values }) => ({
        reviews: [
            { results: [], count: 0, offset: 0 } as CountedPaginatedResponse<TraceReview>,
            {
                loadReviews: async ({ debounce }, breakpoint) => {
                    if (debounce && values.reviews.results.length > 0) {
                        await breakpoint(300)
                    }

                    const { filters } = values

                    return traceReviewsApi.list({
                        ...traceReviewListParamsFromFilters(filters),
                        offset: Math.max(0, (filters.page - 1) * TRACE_REVIEWS_PER_PAGE),
                        limit: TRACE_REVIEWS_PER_PAGE,
                    })
                },
            },
        ],

        scoreDefinitionOptions: [
            [] as ScoreDefinitionApi[],
            {
                loadScoreDefinitionOptions: async () => {
                    const response = await aiObservabilityScoreDefinitionsList(String(ApiConfig.getCurrentTeamId()), {
                        archived: false,
                        order_by: 'name',
                        limit: 1000,
                    })

                    return response.results
                },
            },
        ],
    })),

    selectors({
        filters: [
            (s) => [s.rawFilters],
            (rawFilters: Partial<TraceReviewFilters> | null): TraceReviewFilters => cleanFilters(rawFilters || {}),
        ],

        count: [(s) => [s.reviews], (reviews: CountedPaginatedResponse<TraceReview>) => reviews.count],

        sorting: [
            (s) => [s.filters],
            (filters: TraceReviewFilters): Sorting | null =>
                filters.order_by.startsWith('-')
                    ? { columnKey: filters.order_by.slice(1), order: -1 }
                    : { columnKey: filters.order_by, order: 1 },
        ],

        pagination: [
            (s) => [s.filters, s.count],
            (filters: TraceReviewFilters, count: number): PaginationManual => ({
                controlled: true,
                pageSize: TRACE_REVIEWS_PER_PAGE,
                currentPage: filters.page,
                entryCount: count,
            }),
        ],

        reviewCountLabel: [
            (s) => [s.filters, s.count],
            (filters: TraceReviewFilters, count: number): string => {
                const start = (filters.page - 1) * TRACE_REVIEWS_PER_PAGE + 1
                const end = Math.min(filters.page * TRACE_REVIEWS_PER_PAGE, count)

                return count === 0 ? '0 reviews' : `${start}-${end} of ${pluralize(count, 'review')}`
            },
        ],

        exportPath: [
            (s) => [s.filters],
            (filters: TraceReviewFilters): string =>
                buildTraceReviewsListUrl(undefined, traceReviewListParamsFromFilters(filters)),
        ],
    }),

    listeners(({ asyncActions, values, selectors }) => ({
        setFilters: async ({ debounce }, _, __, previousState) => {
            const oldFilters = selectors.filters(previousState)

            if (!objectsEqual(oldFilters, values.filters)) {
                await asyncActions.loadReviews(debounce)
            }
        },
        copyReviewsToClipboard: async ({ format }, breakpoint) => {
            try {
                const { reviews, total, truncated } = await fetchAllReviewsForExport(values.filters)
                breakpoint()

                if (total === 0) {
                    lemonToast.error('No reviews to copy!')
                    return
                }

                if (truncated) {
                    lemonToast.warning(
                        `Too many reviews to copy to clipboard (${total}). Use "Export current columns" to download a file instead.`
                    )
                    return
                }

                const payload = formatReviewsForClipboard(reviews, format)
                await copyToClipboard(payload, 'reviews')
                breakpoint()
            } catch (error) {
                if (error instanceof Error && isBreakpoint(error)) {
                    return
                }
                lemonToast.error('Copy failed!')
            }
        },
    })),

    trackedActionToUrl(({ values }) => ({
        setFilters: () => {
            const nextValues = { ...getUrlFilters(values.filters), human_reviews_tab: 'reviews' }
            const urlValues = {
                ...getUrlFilters(filtersFromUrl(router.values.searchParams)),
                human_reviews_tab: router.values.searchParams.human_reviews_tab === 'reviews' ? 'reviews' : undefined,
            }

            if (!objectsEqual(nextValues, urlValues)) {
                // Spread current params first — this logic only owns the review_* /
                // human_reviews_tab params and must not strip anyone else's.
                return [
                    urls.aiObservabilityReviews(),
                    { ...router.values.searchParams, ...nextValues },
                    {},
                    { replace: true },
                ]
            }
        },
    })),

    urlToAction(({ actions, values }) => ({
        [urls.aiObservabilityReviews()]: (_, searchParams, __, { method }) => {
            const newFilters = filtersFromUrl(searchParams)

            if (!objectsEqual(values.filters, newFilters)) {
                actions.setFilters(newFilters, false)
            } else if (method !== 'REPLACE') {
                actions.loadReviews(false)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadReviews()
        actions.loadScoreDefinitionOptions()
    }),
])
