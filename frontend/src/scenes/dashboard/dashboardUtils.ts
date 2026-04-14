import { ResponsiveLayouts } from 'react-grid-layout'

import { lemonToast } from '@posthog/lemon-ui'

import api, { ApiMethodOptions, getJSONOrNull } from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { currentSessionId } from 'lib/internalMetrics'
import { dateStringToDayJs, isDate, objectClean, shouldCancelQuery, toParams } from 'lib/utils'
import { accessLevelSatisfied } from 'lib/utils/accessControlUtils'

import { getQueryBasedInsightModel } from '~/queries/nodes/InsightViz/utils'
import { pollForResults } from '~/queries/query'
import { DashboardFilter, HogQLVariable, TileFilters } from '~/queries/schema/schema-general'
import {
    AccessControlLevel,
    AccessControlResourceType,
    DashboardLayoutSize,
    DashboardTemplateEditorType,
    DashboardTile,
    DashboardType,
    DashboardWidgetType,
    InsightModel,
    QueryBasedInsightModel,
    TileLayout,
} from '~/types'

/** Shape used for staff JSON export, customer save-as-template, and API `create_from_template_json`. */
export function dashboardToSaveableTemplate(
    dashboard: DashboardType<InsightModel> | null | undefined
): DashboardTemplateEditorType | undefined {
    if (!dashboard) {
        return undefined
    }
    return {
        template_name: dashboard.name,
        dashboard_description: dashboard.description,
        dashboard_filters: dashboard.filters,
        tags: dashboard.tags || [],
        tiles: dashboard.tiles
            .filter((tile) => !tile.error)
            .map((tile) => {
                if (tile.text) {
                    return {
                        type: 'TEXT' as const,
                        body: tile.text.body,
                        layouts: tile.layouts,
                        color: tile.color,
                    }
                }
                if (tile.insight) {
                    return {
                        type: 'INSIGHT' as const,
                        name: tile.insight.name,
                        description: tile.insight.description || '',
                        query: tile.insight.query,
                        layouts: tile.layouts,
                        color: tile.color,
                    }
                }
                if (tile.button_tile) {
                    return {
                        button_tile: {
                            url: tile.button_tile.url,
                            text: tile.button_tile.text,
                            placement: tile.button_tile.placement,
                            style: tile.button_tile.style,
                        },
                        layouts: tile.layouts,
                        color: tile.color,
                    }
                }
                throw new Error('Unknown tile type')
            }),
        variables: [],
    }
}

/** Which widget payload is set on a dashboard tile row. Add a branch per `DashboardWidgetType` when new tile kinds ship. */
export function getDashboardWidgetType(
    tile: Pick<DashboardTile<InsightModel | QueryBasedInsightModel>, 'insight' | 'text' | 'button_tile'>
): DashboardWidgetType {
    if (tile.insight) {
        return 'insight'
    }
    if (tile.text) {
        return 'text'
    }
    if (tile.button_tile) {
        return 'button_tile'
    }

    throw new Error(
        'Dashboard tile has no widget payload. If a new widget type was added to `DashboardTile`, handle it in getDashboardWidgetType.'
    )
}

export const BREAKPOINTS: Record<DashboardLayoutSize, number> = {
    sm: 768,
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

export const DEFAULT_AUTO_PREVIEW_TILE_LIMIT = 10

const RATE_LIMIT_ERROR_MESSAGE = 'concurrency_limit_exceeded'

export const AUTO_REFRESH_INITIAL_INTERVAL_SECONDS = 1800
export const QUICK_FILTER_DEBOUNCE_MS = 1500

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

export const layoutsByTile = (layouts: ResponsiveLayouts): Record<string, Record<DashboardLayoutSize, TileLayout>> => {
    const itemLayouts: Record<string, Record<DashboardLayoutSize, TileLayout>> = {}

    Object.entries(layouts).forEach(([col, layout]) => {
        layout?.forEach((layoutItem) => {
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

    const raw = searchParams[SEARCH_PARAM_QUERY_VARIABLES_KEY]
    if (raw) {
        try {
            // kea-router auto-parses JSON-like values from the URL, so the value
            // may already be an object when the URL doesn't have a trailing space.
            const parsedVariables = typeof raw === 'string' ? JSON.parse(raw) : raw
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

    const raw = searchParams[SEARCH_PARAM_FILTERS_KEY]
    if (raw) {
        try {
            // kea-router auto-parses JSON-like values from the URL, so the value
            // may already be an object when the URL doesn't have a trailing space.
            const parsedFilters = typeof raw === 'string' ? JSON.parse(raw) : raw
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
    const combined = filters.reduce((acc, filter) => {
        Object.keys(filter).forEach((key) => {
            const value = (filter as Record<string, any>)[key]
            if (value !== undefined) {
                ;(acc as Record<string, any>)[key] = value
            }
        })
        return acc
    }, {} as DashboardFilter)

    // Strip null values and default-false explicitDate so the serialized
    // output is stable across code paths. Without this, switching date filters
    // can produce {date_from: "-7d", date_to: null, explicitDate: false}
    // instead of just {date_from: "-7d"}, leading to different JSON payloads
    // sent to the backend and potentially different cache key lookups.
    const cleaned: Record<string, any> = {}
    for (const [key, value] of Object.entries(combined)) {
        if (value === null || value === undefined) {
            continue
        }
        if (key === 'explicitDate' && value === false) {
            continue
        }
        cleaned[key] = value
    }
    return cleaned as DashboardFilter
}

/**
 * Check whether a cached tile's data is date-stale — i.e. its `last_refresh` is old enough
 * that relative date filters (e.g. "-7d") would now resolve to a different calendar day.
 *
 * The normal cache staleness check (`cache_target_age`) only considers how old the cache is
 * relative to the query interval (e.g. 6 hours for daily). But for dashboards with relative
 * date filters, a cache from 6 hours ago can still show data starting from a different day
 * than "now" would produce — causing tiles to briefly display mismatched date ranges.
 *
 * Returns true if the tile should be refreshed because the date range has shifted.
 */
export function isTileDateRangeStale(
    filters: DashboardFilter,
    tileLastRefresh: string | null | undefined,
    timezone: string
): boolean {
    // Only relevant when date_from is a relative date string
    if (!filters.date_from || isDate.test(filters.date_from) || filters.date_from === 'all') {
        return false
    }

    if (!tileLastRefresh) {
        return true // No last_refresh means the tile has never been computed
    }

    // Resolve what date_from meant at the time the tile was last refreshed vs now.
    // If they land on different calendar days, the tile's data is showing a shifted range.
    const now = dayjs().tz(timezone)
    const lastRefreshTime = dayjs(tileLastRefresh).tz(timezone)

    const currentDateFrom = dateStringToDayJs(filters.date_from, timezone)
    if (!currentDateFrom) {
        return false
    }

    // Re-resolve the same relative date string but using the tile's last_refresh time as "now".
    // dateStringToDayJs uses dayjs().tz(timezone).startOf('day') as the offset,
    // so we compare by checking if the last_refresh day differs from today's day — which would
    // cause the resolved date_from to shift.
    const lastRefreshDay = lastRefreshTime.startOf('day')
    const currentDay = now.startOf('day')

    // If last_refresh is from a different calendar day, relative dates will resolve differently
    return !lastRefreshDay.isSame(currentDay, 'day')
}
