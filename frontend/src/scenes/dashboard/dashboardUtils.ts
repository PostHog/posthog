import { Layouts } from 'react-grid-layout'

import { lemonToast } from '@posthog/lemon-ui'

import api, { ApiMethodOptions, getJSONOrNull } from 'lib/api'
import { accessLevelSatisfied } from 'lib/components/AccessControlAction'
import { currentSessionId } from 'lib/internalMetrics'
import { objectClean, shouldCancelQuery, toParams } from 'lib/utils'

import { getQueryBasedInsightModel } from '~/queries/nodes/InsightViz/utils'
import { pollForResults } from '~/queries/query'
import { DashboardFilter, HogQLVariable, TileFilters } from '~/queries/schema/schema-general'
import {
    AccessControlLevel,
    AccessControlResourceType,
    DashboardLayoutSize,
    InsightModel,
    QueryBasedInsightModel,
    TileLayout,
} from '~/types'

export const BREAKPOINTS: Record<DashboardLayoutSize, number> = {
    sm: 1024,
    xs: 0,
}
export const BREAKPOINT_COLUMN_COUNTS: Record<DashboardLayoutSize, number> = { sm: 12, xs: 1 }

/**
 * The minimum interval between manual dashboard refreshes.
 * This is used to block the dashboard refresh button.
 */
export const DASHBOARD_MIN_REFRESH_INTERVAL_MINUTES = 15

export const IS_TEST_MODE = process.env.NODE_ENV === 'test'

export const SEARCH_PARAM_QUERY_VARIABLES_KEY = 'query_variables'
export const SEARCH_PARAM_FILTERS_KEY = 'query_filters'

/**
 * Once a dashboard has more tiles than this,
 * we don't automatically preview dashboard date/filter/breakdown changes.
 * Users will need to click the 'Apply and preview filters' button.
 */
export const MAX_TILES_FOR_AUTOPREVIEW = 5

const RATE_LIMIT_ERROR_MESSAGE = 'concurrency_limit_exceeded'

export const AUTO_REFRESH_INITIAL_INTERVAL_SECONDS = 1800

// Helper function for exponential backoff
const wait = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

/**
 * Run a set of tasks **in order** with a limit on the number of concurrent tasks.
 * Important to be in order so that we poll dashboard insights in the
 * same order as they are calculated on the backend.
 *
 * @param tasks - An array of functions that return promises.
 * @param limit - The maximum number of concurrent tasks.
 * @returns A promise that resolves to an array of results from the tasks.
 */
export async function runWithLimit<T>(tasks: (() => Promise<T>)[], limit: number): Promise<T[]> {
    const results: T[] = []
    const activePromises: Set<Promise<void>> = new Set()
    const remainingTasks = [...tasks]

    const startTask = async (task: () => Promise<T>): Promise<void> => {
        const promise = task()
            .then((result) => {
                results.push(result)
            })
            .catch((error) => {
                console.error('Error executing task:', error)
            })
            .finally(() => {
                void activePromises.delete(promise)
            })
        activePromises.add(promise)
        await promise
    }

    while (remainingTasks.length > 0 || activePromises.size > 0) {
        if (activePromises.size < limit && remainingTasks.length > 0) {
            void startTask(remainingTasks.shift()!)
        } else {
            await Promise.race(activePromises)
        }
    }

    return results
}

export const layoutsByTile = (layouts: Layouts): Record<string, Record<DashboardLayoutSize, TileLayout>> => {
    const itemLayouts: Record<string, Record<DashboardLayoutSize, TileLayout>> = {}

    Object.entries(layouts).forEach(([col, layout]) => {
        layout.forEach((layoutItem) => {
            const i = String(layoutItem.i)
            if (!itemLayouts[i]) {
                itemLayouts[i] = {} as Record<DashboardLayoutSize, TileLayout>
            }
            itemLayouts[i][col as DashboardLayoutSize] = layoutItem
        })
    })
    return itemLayouts
}

/**
 * Fetches an insight with a retry and polling mechanism.
 * It first attempts to fetch the insight synchronously. If rate-limited, it retries with exponential backoff.
 * After multiple failed attempts, it switches to asynchronous polling to fetch the result.
 */
export async function getInsightWithRetry(
    currentTeamId: number | null,
    insight: QueryBasedInsightModel,
    dashboardId: number,
    queryId: string,
    refresh: 'force_blocking' | 'blocking',
    methodOptions?: ApiMethodOptions,
    filtersOverride?: DashboardFilter,
    variablesOverride?: Record<string, HogQLVariable>,
    tileFiltersOverride?: TileFilters,
    maxAttempts: number = 5,
    initialDelay: number = 1200
): Promise<QueryBasedInsightModel | null> {
    // Check if user has access to this insight before making API calls
    const canViewInsight = insight.user_access_level
        ? accessLevelSatisfied(AccessControlResourceType.Insight, insight.user_access_level, AccessControlLevel.Viewer)
        : true

    if (!canViewInsight) {
        // Return the insight as-is without making API calls - it should already have minimal data
        return insight
    }

    let attempt = 0

    while (attempt < maxAttempts) {
        try {
            const apiUrl = `api/environments/${currentTeamId}/insights/${insight.id}/?${toParams({
                refresh,
                from_dashboard: dashboardId, // needed to load insight in correct context
                client_query_id: queryId,
                session_id: currentSessionId(),
                ...(filtersOverride ? { filters_override: filtersOverride } : {}),
                ...(variablesOverride ? { variables_override: variablesOverride } : {}),
                ...(tileFiltersOverride ? { tile_filters_override: tileFiltersOverride } : {}),
            })}`
            const insightResponse: Response = await api.getResponse(apiUrl, methodOptions)
            const legacyInsight: InsightModel | null = await getJSONOrNull(insightResponse)
            const result = legacyInsight !== null ? getQueryBasedInsightModel(legacyInsight) : null

            if (result?.query_status?.error_message === RATE_LIMIT_ERROR_MESSAGE) {
                attempt++

                if (attempt >= maxAttempts) {
                    // We've exhausted all attempts, so we need to try the async endpoint.
                    try {
                        const asyncApiUrl = `api/environments/${currentTeamId}/insights/${insight.id}/?${toParams({
                            refresh: 'force_async',
                            from_dashboard: dashboardId,
                            client_query_id: queryId,
                            session_id: currentSessionId(),
                            ...(filtersOverride ? { filters_override: filtersOverride } : {}),
                            ...(variablesOverride ? { variables_override: variablesOverride } : {}),
                            ...(tileFiltersOverride ? { tile_filters_override: tileFiltersOverride } : {}),
                        })}`
                        // The async call returns an insight with a query_status object
                        const insightResponse = await api.get(asyncApiUrl, methodOptions)

                        if (insightResponse?.query_status?.id) {
                            const finalStatus = await pollForResults(insightResponse.query_status.id, methodOptions)
                            if (finalStatus.complete && !finalStatus.error) {
                                const cacheUrl = `api/environments/${currentTeamId}/insights/${insight.id}/?${toParams({
                                    refresh: 'force_cache',
                                    from_dashboard: dashboardId,
                                    client_query_id: queryId,
                                    session_id: currentSessionId(),
                                    ...(filtersOverride ? { filters_override: filtersOverride } : {}),
                                    ...(variablesOverride ? { variables_override: variablesOverride } : {}),
                                    ...(tileFiltersOverride ? { tile_filters_override: tileFiltersOverride } : {}),
                                })}`
                                const refreshedInsightResponse: Response = await api.getResponse(
                                    cacheUrl,
                                    methodOptions
                                )
                                const legacyInsight: InsightModel | null = await getJSONOrNull(refreshedInsightResponse)
                                if (legacyInsight) {
                                    const queryBasedInsight = getQueryBasedInsightModel(legacyInsight)
                                    return { ...queryBasedInsight, query_status: finalStatus }
                                }
                            }
                        }

                        // If something went wrong with async, show an error.
                        lemonToast.error(
                            `Insight "${
                                insight.name || insight.derived_name
                            }" failed to load due to high load. Please try again later.`,
                            { toastId: `insight-concurrency-error-${insight.short_id}` }
                        )
                        return result
                    } catch (e) {
                        if (shouldCancelQuery(e)) {
                            throw e // Re-throw cancellation errors
                        }
                        // if polling throws, show an error.
                        lemonToast.error(
                            `Insight "${
                                insight.name || insight.derived_name
                            }" failed to load due to high load. Please try again later.`,
                            { toastId: `insight-concurrency-error-${insight.short_id}` }
                        )
                        return result
                    }
                }
                const delay = initialDelay * Math.pow(1.2, attempt - 1) // Exponential backoff
                await wait(delay)
                continue // Retry
            }

            return result
        } catch (e: any) {
            if (shouldCancelQuery(e)) {
                throw e // Re-throw cancellation errors
            }

            attempt++
            if (attempt >= maxAttempts) {
                throw e // Re-throw the error after max attempts
            }

            const delay = initialDelay * Math.pow(1.2, attempt - 1)
            await wait(delay)
        }
    }

    return null
}

export const parseURLVariables = (searchParams: Record<string, any>): Record<string, Partial<HogQLVariable>> => {
    const variables: Record<string, Partial<HogQLVariable>> = {}

    if (searchParams[SEARCH_PARAM_QUERY_VARIABLES_KEY]) {
        try {
            const parsedVariables = JSON.parse(searchParams[SEARCH_PARAM_QUERY_VARIABLES_KEY])
            Object.assign(variables, parsedVariables)
        } catch (e) {
            console.error('Failed to parse query_variables from URL:', e)
        }
    }

    return variables
}

export const encodeURLVariables = (variables: Record<string, string>): Record<string, string> => {
    const encodedVariables: Record<string, string> = {}

    if (Object.keys(variables).length > 0) {
        encodedVariables[SEARCH_PARAM_QUERY_VARIABLES_KEY] = JSON.stringify(variables)
    }

    return encodedVariables
}

export const parseURLFilters = (searchParams: Record<string, any>): DashboardFilter => {
    const filters: DashboardFilter = {}

    if (searchParams[SEARCH_PARAM_FILTERS_KEY]) {
        try {
            const parsedFilters = JSON.parse(searchParams[SEARCH_PARAM_FILTERS_KEY])
            Object.assign(filters, parsedFilters)
        } catch (e) {
            console.error(`Failed to parse ${SEARCH_PARAM_FILTERS_KEY} from URL:`, e)
        }
    }

    return filters
}

export const encodeURLFilters = (filters: DashboardFilter): Record<string, string> => {
    const encodedFilters: Record<string, string> = {}

    if (Object.keys(filters).length > 0) {
        encodedFilters[SEARCH_PARAM_FILTERS_KEY] = JSON.stringify(objectClean(filters as Record<string, unknown>))
    }

    return encodedFilters
}

export function combineDashboardFilters(...filters: DashboardFilter[]): DashboardFilter {
    return filters.reduce((combined, filter) => {
        Object.keys(filter).forEach((key) => {
            const value = (filter as Record<string, any>)[key]
            if (value !== undefined) {
                ;(combined as Record<string, any>)[key] = value
            }
        })
        return combined
    }, {} as DashboardFilter)
}
