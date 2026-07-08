import { actions, afterMount, beforeUnmount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { trackedActionToUrl } from 'lib/logic/scenes/trackedActionToUrl'
import { objectsEqual } from 'lib/utils/objects'
import { sceneLogic } from 'scenes/sceneLogic'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { isAnyPropertyFilters } from '~/queries/schema-guards'
import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, Breadcrumb } from '~/types'

import type { aiObservabilitySharedLogicType } from './aiObservabilitySharedLogicType'
import { AI_OBSERVABILITY_CLUSTER_URL_PATTERN } from './clusters/constants'
import { parserRecipesLogic } from './settings/parserRecipesLogic'
import { hasRecentAIEvents } from './utils/aiEvents'

export const AI_OBSERVABILITY_DATA_COLLECTION_NODE_ID = 'ai-observability-data'

// Params this logic owns and rewrites when its state changes. Everything else is
// passed through untouched — other logics (e.g. reviews' `review_*`, queues'
// `queue_*`) own their params, so an allowlist here must never strip them.
// `trace_search`, not `search`: the trace view owns `search` for its in-trace
// search, and back navigation would leak it into the list's content filter.
const SHARED_PARAMS = new Set(['filters', 'date_from', 'date_to', 'filter_test_accounts', 'trace_search'])
// Params from the trace view that must not linger on list-tab URLs.
const STALE_PARAMS = new Set(['event', 'timestamp', 'msg'])

export type AIObservabilityTabId =
    | 'dashboard'
    | 'generations'
    | 'reviews'
    | 'traces'
    | 'users'
    | 'errors'
    | 'tools'
    | 'sentiment'
    | 'sessions'
    | 'playground'
    | 'datasets'
    | 'evaluations'
    | 'prompts'
    | 'clusters'

export type SortDirection = 'ASC' | 'DESC'

export interface SortState {
    column: string
    direction: SortDirection
}

const INITIAL_DASHBOARD_DATE_FROM = '-7d' as string | null
const INITIAL_EVENTS_DATE_FROM = '-1h' as string | null
const INITIAL_DATE_TO = null as string | null

export interface AIObservabilitySharedLogicProps {
    logicKey?: string
    personId?: string
    group?: {
        groupKey: string
        groupTypeIndex: number
    }
}

export interface ApplyUrlStatePayload {
    propertyFilters: AnyPropertyFilter[]
    dateFrom: string | null
    dateTo: string | null
    shouldFilterTestAccounts: boolean
    searchQuery?: string
    datesChanged: boolean
}

interface BuildApplyUrlStatePayloadInput {
    dateFrom: string | null
    dateTo: string | null
    shouldFilterTestAccounts: boolean
    propertyFilters: AnyPropertyFilter[]
    searchQuery?: string
    currentDateFilter: { dateFrom: string | null; dateTo: string | null }
    currentPropertyFilters: AnyPropertyFilter[]
}

/**
 * Build the payload for `applyUrlState` from a DataTable's query source. Preserves
 * reference identity on unchanged `propertyFilters` so Kea selectors short-circuit,
 * and computes `datesChanged` so the dashboard-tab date picker is not overwritten
 * when only filters change.
 */
export function buildApplyUrlStatePayload({
    dateFrom,
    dateTo,
    shouldFilterTestAccounts,
    propertyFilters,
    searchQuery,
    currentDateFilter,
    currentPropertyFilters,
}: BuildApplyUrlStatePayloadInput): ApplyUrlStatePayload {
    return {
        propertyFilters: objectsEqual(propertyFilters, currentPropertyFilters)
            ? currentPropertyFilters
            : propertyFilters,
        dateFrom,
        dateTo,
        shouldFilterTestAccounts,
        searchQuery,
        datesChanged: dateFrom !== currentDateFilter.dateFrom || dateTo !== currentDateFilter.dateTo,
    }
}

export const aiObservabilitySharedLogic = kea<aiObservabilitySharedLogicType>([
    path(['products', 'ai_observability', 'frontend', 'aiObservabilitySharedLogic']),
    props({} as AIObservabilitySharedLogicProps),
    key((props: AIObservabilitySharedLogicProps) => `${props?.personId || 'aiObservabilityScene'}`),
    connect(() => ({
        // Mount the parser-recipe logic so a team's custom recipes reach the trace-rendering
        // normalizer on any AI observability page, not just the settings scene.
        logic: [parserRecipesLogic],
        values: [
            sceneLogic,
            ['sceneKey'],
            featureFlagLogic,
            ['featureFlags'],
            userLogic,
            ['user'],
            filterTestAccountsDefaultsLogic,
            ['filterTestAccountsDefault'],
        ],
        actions: [teamLogic, ['addProductIntent'], filterTestAccountsDefaultsLogic, ['setLocalDefault']],
    })),

    actions({
        setDates: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setShouldFilterTestAccounts: (shouldFilterTestAccounts: boolean) => ({ shouldFilterTestAccounts }),
        setShouldFilterSupportTraces: (shouldFilterSupportTraces: boolean) => ({ shouldFilterSupportTraces }),
        setPropertyFilters: (propertyFilters: AnyPropertyFilter[]) => ({ propertyFilters }),
        setSearchQuery: (searchQuery: string) => ({ searchQuery }),
        // Batched action for URL-to-state sync. Dispatched once from urlToAction
        // or scene-level setQuery handlers instead of multiple individual actions,
        // producing a single actionToUrl URL change instead of 3-4 separate ones.
        applyUrlState: (state: ApplyUrlStatePayload) => state,
    }),

    reducers({
        dateFilter: [
            {
                dateFrom: INITIAL_EVENTS_DATE_FROM,
                dateTo: INITIAL_DATE_TO,
            },
            {
                setDates: (_, { dateFrom, dateTo }) => ({ dateFrom, dateTo }),
                applyUrlState: (_, { dateFrom, dateTo }) => ({ dateFrom, dateTo }),
            },
        ],

        dashboardDateFilter: [
            {
                dateFrom: INITIAL_DASHBOARD_DATE_FROM,
                dateTo: INITIAL_DATE_TO,
            },
            {
                setDates: (_, { dateFrom, dateTo }) => ({ dateFrom, dateTo }),
                applyUrlState: (state, { dateFrom, dateTo, datesChanged }) =>
                    datesChanged ? { dateFrom, dateTo } : state,
            },
        ],

        shouldFilterTestAccounts: [
            false,
            {
                setShouldFilterTestAccounts: (_, { shouldFilterTestAccounts }) => shouldFilterTestAccounts,
                applyUrlState: (_, { shouldFilterTestAccounts }) => shouldFilterTestAccounts,
            },
        ],

        shouldFilterSupportTraces: [
            false, // For impersonated users, default to NOT filtering (show support traces)
            {
                setShouldFilterSupportTraces: (_, { shouldFilterSupportTraces }) => shouldFilterSupportTraces,
            },
        ],

        propertyFilters: [
            [] as AnyPropertyFilter[],
            {
                setPropertyFilters: (_, { propertyFilters }) => propertyFilters,
                applyUrlState: (_, { propertyFilters }) => propertyFilters,
            },
        ],

        searchQuery: [
            '' as string,
            {
                setSearchQuery: (_, { searchQuery }) => searchQuery,
                applyUrlState: (state, { searchQuery }) => searchQuery ?? state,
            },
        ],
    }),

    loaders(() => ({
        hasSentAiEvent: {
            __default: undefined as boolean | undefined,
            loadAIEventDefinition: async (): Promise<boolean> => {
                return hasRecentAIEvents()
            },
        },
    })),

    listeners(({ actions, values }) => ({
        loadAIEventDefinitionSuccess: ({ hasSentAiEvent }) => {
            if (hasSentAiEvent) {
                globalSetupLogic.findMounted()?.actions.markTaskAsCompleted(SetupTaskId.IngestFirstLlmEvent)
            }
        },
        setShouldFilterTestAccounts: ({ shouldFilterTestAccounts }) => {
            const divergesFromEffectiveDefault = shouldFilterTestAccounts !== values.filterTestAccountsDefault
            if (divergesFromEffectiveDefault) {
                actions.setLocalDefault(shouldFilterTestAccounts)
            }
        },
    })),

    selectors({
        activeTab: [
            (s) => [s.sceneKey],
            (sceneKey): AIObservabilityTabId => {
                if (sceneKey === 'aiObservabilityGenerations') {
                    return 'generations'
                } else if (sceneKey === 'aiObservabilityReviews') {
                    return 'reviews'
                } else if (sceneKey === 'aiObservabilityTraces') {
                    return 'traces'
                } else if (sceneKey === 'aiObservabilityUsers') {
                    return 'users'
                } else if (sceneKey === 'aiObservabilityErrors') {
                    return 'errors'
                } else if (sceneKey === 'aiObservabilityTools') {
                    return 'tools'
                } else if (sceneKey === 'aiObservabilitySentiment') {
                    return 'sentiment'
                } else if (sceneKey === 'aiObservabilitySessions') {
                    return 'sessions'
                } else if (sceneKey === 'aiObservabilityPlayground') {
                    return 'playground'
                } else if (sceneKey === 'aiObservabilityDatasets') {
                    return 'datasets'
                } else if (sceneKey === 'aiObservabilityEvaluations') {
                    return 'evaluations'
                } else if (sceneKey === 'aiObservabilityPrompts') {
                    return 'prompts'
                } else if (sceneKey === 'aiObservabilityClusters') {
                    return 'clusters'
                }

                return 'dashboard'
            },
        ],

        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => {
                return [
                    {
                        key: 'llm_analytics',
                        name: 'AI observability',
                        iconType: 'llm_analytics',
                    },
                ]
            },
        ],
    }),

    urlToAction(({ actions, values, cache }) => {
        function applySearchParams(searchParams: Record<string, unknown>): void {
            const { filters, date_from, date_to, filter_test_accounts, trace_search } = searchParams

            const parsedFilters = isAnyPropertyFilters(filters) ? filters : []
            const newDateFrom = (date_from as string | null) || INITIAL_EVENTS_DATE_FROM
            const newDateTo = (date_to as string | null) || INITIAL_DATE_TO
            const filterTestAccountsValue = [true, 'true', 1, '1'].includes(
                filter_test_accounts as string | number | boolean
            )
            const newSearchQuery = typeof trace_search === 'string' ? trace_search : ''

            const filtersChanged = !objectsEqual(parsedFilters, values.propertyFilters)
            const datesChanged = newDateFrom !== values.dateFilter.dateFrom || newDateTo !== values.dateFilter.dateTo
            const testAccountsChanged = filterTestAccountsValue !== values.shouldFilterTestAccounts
            const searchQueryChanged = newSearchQuery !== values.searchQuery

            if (filtersChanged || datesChanged || testAccountsChanged || searchQueryChanged) {
                // Dispatch a single batched action so actionToUrl produces one URL
                // change instead of up to 3 separate ones. The actionToUrl handler
                // for applyUrlState rewrites the shared params and drops stale
                // trace-view params, passing all other params through.
                actions.applyUrlState({
                    propertyFilters: parsedFilters,
                    dateFrom: newDateFrom,
                    dateTo: newDateTo,
                    shouldFilterTestAccounts: filterTestAccountsValue,
                    searchQuery: newSearchQuery,
                    datesChanged,
                })
            } else {
                // No state changed, but stale params from the trace view may
                // still need stripping (e.g. event, timestamp, msg).
                const hasStaleParams = Object.keys(searchParams).some((key) => STALE_PARAMS.has(key))
                if (hasStaleParams) {
                    const cleanParams: Record<string, unknown> = {}
                    for (const [key, value] of Object.entries(searchParams)) {
                        if (!STALE_PARAMS.has(key)) {
                            cleanParams[key] = value
                        }
                    }
                    router.actions.replace(router.values.location.pathname, cleanParams)
                }
            }
        }

        function clearDashboardTimer(): void {
            clearTimeout(cache.dashboardDwellTimer)
            cache.dashboardDwellTimer = undefined
        }

        function startDashboardTimer(): void {
            clearDashboardTimer()
            cache.dashboardDwellTimer = setTimeout(() => {
                actions.addProductIntent({
                    product_type: ProductKey.AI_OBSERVABILITY,
                    intent_context: ProductIntentContext.LLM_ANALYTICS_VIEWED,
                })
            }, 15000)
        }

        function applyNonDashboard(searchParams: Record<string, unknown>): void {
            clearDashboardTimer()
            applySearchParams(searchParams)
        }

        return {
            [urls.aiObservabilityDashboard()]: (_, searchParams) => {
                applySearchParams(searchParams)
                startDashboardTimer()
            },
            [urls.aiObservabilityGenerations()]: (_, searchParams) => applyNonDashboard(searchParams),
            [urls.aiObservabilityReviews()]: (_, searchParams) => applyNonDashboard(searchParams),
            [urls.aiObservabilityTraces()]: (_, searchParams) => applyNonDashboard(searchParams),
            [urls.aiObservabilityUsers()]: (_, searchParams) => applyNonDashboard(searchParams),
            [urls.aiObservabilityErrors()]: (_, searchParams) => applyNonDashboard(searchParams),
            [urls.aiObservabilityTools()]: (_, searchParams) => applyNonDashboard(searchParams),
            [urls.aiObservabilitySentiment()]: (_, searchParams) => applyNonDashboard(searchParams),
            [urls.aiObservabilitySessions()]: (_, searchParams) => applyNonDashboard(searchParams),
            '/ai-observability/sessions/:id': (_, searchParams) => applyNonDashboard(searchParams),
            [urls.aiObservabilityPlayground()]: (_, searchParams) => applyNonDashboard(searchParams),
            // Cluster list and detail both honor the same `filters` / `filter_test_accounts`
            // params so deep links from generations/traces tabs carry their filter set through.
            [urls.aiObservabilityClusters()]: (_, searchParams) => applyNonDashboard(searchParams),
            '/ai-observability/clusters/:runId': (_, searchParams) => applyNonDashboard(searchParams),
            [AI_OBSERVABILITY_CLUSTER_URL_PATTERN]: (_, searchParams) => applyNonDashboard(searchParams),
        }
    }),

    trackedActionToUrl(() => {
        // Pass through params owned by other logics (e.g. review_*, queue_*) —
        // only rewrite the shared params and drop stale trace-view params.
        function passthroughSearchParams(): Record<string, unknown> {
            const passthrough: Record<string, unknown> = {}
            for (const [key, value] of Object.entries(router.values.searchParams)) {
                if (!SHARED_PARAMS.has(key) && !STALE_PARAMS.has(key)) {
                    passthrough[key] = value
                }
            }
            return passthrough
        }

        function sharedSearchParams(): Record<string, unknown> {
            const { filters, date_from, date_to, filter_test_accounts, trace_search } = router.values.searchParams
            return { ...passthroughSearchParams(), filters, date_from, date_to, filter_test_accounts, trace_search }
        }

        return {
            applyUrlState: ({ propertyFilters, dateFrom, dateTo, shouldFilterTestAccounts, searchQuery }) => [
                router.values.location.pathname,
                {
                    ...passthroughSearchParams(),
                    filters: propertyFilters.length > 0 ? propertyFilters : undefined,
                    date_from: dateFrom === INITIAL_EVENTS_DATE_FROM ? undefined : dateFrom || undefined,
                    date_to: dateTo || undefined,
                    filter_test_accounts: shouldFilterTestAccounts ? 'true' : undefined,
                    trace_search:
                        (searchQuery ?? (router.values.searchParams.trace_search as string | undefined)) || undefined,
                },
            ],
            setPropertyFilters: ({ propertyFilters }) => [
                router.values.location.pathname,
                {
                    ...sharedSearchParams(),
                    filters: propertyFilters.length > 0 ? propertyFilters : undefined,
                },
            ],
            setDates: ({ dateFrom, dateTo }) => [
                router.values.location.pathname,
                {
                    ...sharedSearchParams(),
                    date_from: dateFrom === INITIAL_EVENTS_DATE_FROM ? undefined : dateFrom || undefined,
                    date_to: dateTo || undefined,
                },
            ],
            setShouldFilterTestAccounts: ({ shouldFilterTestAccounts }) => [
                router.values.location.pathname,
                {
                    ...sharedSearchParams(),
                    filter_test_accounts: shouldFilterTestAccounts ? 'true' : undefined,
                },
            ],
            setSearchQuery: ({ searchQuery }) => [
                router.values.location.pathname,
                {
                    ...sharedSearchParams(),
                    trace_search: searchQuery || undefined,
                },
            ],
        }
    }),

    afterMount(({ actions, values }) => {
        actions.loadAIEventDefinition()
        globalSetupLogic.findMounted()?.actions.markTaskAsCompleted(SetupTaskId.TrackCosts)

        const urlHasTestAccountsParam = 'filter_test_accounts' in router.values.searchParams
        if (!urlHasTestAccountsParam && values.filterTestAccountsDefault !== values.shouldFilterTestAccounts) {
            actions.setShouldFilterTestAccounts(values.filterTestAccountsDefault)
        }
    }),

    beforeUnmount(({ cache }) => {
        clearTimeout(cache.dashboardDwellTimer)
    }),
])
