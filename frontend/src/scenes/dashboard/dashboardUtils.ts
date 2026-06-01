import { ResponsiveLayouts } from 'react-grid-layout'

import { lemonToast } from '@posthog/lemon-ui'

import api, { ApiMethodOptions, getJSONOrNull } from 'lib/api'
import type { Dayjs } from 'lib/dayjs'
import { currentSessionId } from 'lib/internalMetrics'
import { objectClean, shouldCancelQuery, toParams } from 'lib/utils'
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

/**
 * Cold-start one-shot threshold: if data is older than this when a shared dashboard loads,
 * trigger one immediate force_blocking refresh. Aligned with the periodic interval and the
 * backend throttle (`SHARED_FORCE_BLOCKING_MIN_AGE`).
 */
export const SHARED_DASHBOARD_AUTO_FORCE_IF_STALE_MINUTES = AUTO_REFRESH_INITIAL_INTERVAL_SECONDS / 60

function staleAgeMinutes(effectiveLastRefresh: Dayjs | null): number | null {
    if (!effectiveLastRefresh) {
        return null
    }
    if (!effectiveLastRefresh.isValid()) {
        return null
    }
    const ms = Number(effectiveLastRefresh.valueOf())
    if (!Number.isFinite(ms)) {
        return null
    }
    return (Date.now() - ms) / 60_000
}

export function shouldSharedDashboardAutoForceForStaleTime(effectiveLastRefresh: Dayjs | null): boolean {
    const ageMinutes = staleAgeMinutes(effectiveLastRefresh)
    return ageMinutes !== null && ageMinutes >= SHARED_DASHBOARD_AUTO_FORCE_IF_STALE_MINUTES
}

/**
 * Trigger one force_blocking refresh on initial shared-dashboard load if the stalest tile is too old.
 * Idempotent across reloads since the follow-up run uses `forceRefresh` + non-initial action.
 */
export function scheduleSharedDashboardStaleAutoForceIfEligible(options: {
    effectiveLastRefresh: Dayjs | null
    triggerDashboardRefresh: () => void
}): void {
    const { effectiveLastRefresh, triggerDashboardRefresh } = options
    if (!shouldSharedDashboardAutoForceForStaleTime(effectiveLastRefresh)) {
        return
    }
    queueMicrotask(() => {
        triggerDashboardRefresh()
    })
}

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
