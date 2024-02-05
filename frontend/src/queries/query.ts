import api, { ApiMethodOptions } from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { now } from 'lib/dayjs'
import { currentSessionId } from 'lib/internalMetrics'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { delay, flattenObject, toParams } from 'lib/utils'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import posthog from 'posthog-js'
import {
    filterTrendsClientSideParams,
    isFunnelsFilter,
    isLifecycleFilter,
    isPathsFilter,
    isRetentionFilter,
    isStickinessFilter,
    isTrendsFilter,
} from 'scenes/insights/sharedUtils'

import { AnyPartialFilterType, OnlineExportContext, QueryExportContext } from '~/types'

import { queryNodeToFilter } from './nodes/InsightQuery/utils/queryNodeToFilter'
import { DataNode, HogQLQuery, HogQLQueryResponse, NodeKind, PersonsNode } from './schema'
import {
    isActorsQuery,
    isDataTableNode,
    isDataVisualizationNode,
    isEventsQuery,
    isFunnelsQuery,
    isHogQLQuery,
    isInsightQueryNode,
    isInsightVizNode,
    isLifecycleQuery,
    isPathsQuery,
    isPersonsNode,
    isRetentionQuery,
    isStickinessQuery,
    isTimeToSeeDataQuery,
    isTimeToSeeDataSessionsNode,
    isTimeToSeeDataSessionsQuery,
    isTrendsQuery,
} from './utils'

const QUERY_ASYNC_MAX_INTERVAL_SECONDS = 5
const QUERY_ASYNC_TOTAL_POLL_SECONDS = 300

//get export context for a given query
export function queryExportContext<N extends DataNode = DataNode>(
    query: N,
    methodOptions?: ApiMethodOptions,
    refresh?: boolean
): OnlineExportContext | QueryExportContext {
    if (isInsightVizNode(query)) {
        return queryExportContext(query.source, methodOptions, refresh)
    } else if (isDataTableNode(query)) {
        return queryExportContext(query.source, methodOptions, refresh)
    } else if (isDataVisualizationNode(query)) {
        return queryExportContext(query.source, methodOptions, refresh)
    } else if (isEventsQuery(query) || isActorsQuery(query)) {
        return {
            source: query,
        }
    } else if (isHogQLQuery(query)) {
        return { source: query }
    } else if (isPersonsNode(query)) {
        return { path: getPersonsEndpoint(query) }
    } else if (isInsightQueryNode(query)) {
        return legacyInsightQueryExportContext({
            filters: queryNodeToFilter(query),
            currentTeamId: getCurrentTeamId(),
            refresh,
        })
    } else if (isTimeToSeeDataSessionsQuery(query)) {
        return {
            path: '/api/time_to_see_data/sessions',
            method: 'POST',
            body: {
                team_id: query.teamId ?? getCurrentTeamId(),
            },
        }
    } else if (isTimeToSeeDataQuery(query)) {
        return {
            path: '/api/time_to_see_data/session_events',
            method: 'POST',
            body: {
                team_id: query.teamId ?? getCurrentTeamId(),
                session_id: query.sessionId ?? currentSessionId(),
                session_start: query.sessionStart ?? now().subtract(1, 'day').toISOString(),
                session_end: query.sessionEnd ?? now().toISOString(),
            },
        }
    } else if (isTimeToSeeDataSessionsNode(query)) {
        return {
            path: '/api/time_to_see_data/session_events',
            method: 'POST',
            body: {
                team_id: query.source.teamId ?? getCurrentTeamId(),
                session_id: query.source.sessionId ?? currentSessionId(),
                session_start: query.source.sessionStart ?? now().subtract(1, 'day').toISOString(),
                session_end: query.source.sessionEnd ?? now().toISOString(),
            },
        }
    }
    throw new Error(`Unsupported query: ${query.kind}`)
}

/**
 * Execute a query node and return the response, use async query if enabled
 */
async function executeQuery<N extends DataNode = DataNode>(
    queryNode: N,
    methodOptions?: ApiMethodOptions,
    refresh?: boolean,
    queryId?: string
): Promise<NonNullable<N['response']>> {
    const queryAsyncEnabled = Boolean(featureFlagLogic.findMounted()?.values.featureFlags?.[FEATURE_FLAGS.QUERY_ASYNC])
    const excludedKinds = ['HogQLMetadata', 'EventsQuery']
    const queryAsync = queryAsyncEnabled && !excludedKinds.includes(queryNode.kind)
    const response = await api.query(queryNode, methodOptions, queryId, refresh, queryAsync)

    if (!queryAsync || !response.query_async) {
        return response
    }

    const pollStart = performance.now()
    let currentDelay = 300 // start low, because all queries will take at minimum this

    while (performance.now() - pollStart < QUERY_ASYNC_TOTAL_POLL_SECONDS * 1000) {
        await delay(currentDelay, methodOptions?.signal)
        currentDelay = Math.min(currentDelay * 2, QUERY_ASYNC_MAX_INTERVAL_SECONDS * 1000)

        const statusResponse = await api.queryStatus.get(response.id)

        if (statusResponse.complete || statusResponse.error) {
            return statusResponse.results
        }
    }
    throw new Error('Query timed out')
}

// Return data for a given query
export async function query<N extends DataNode = DataNode>(
    queryNode: N,
    methodOptions?: ApiMethodOptions,
    refresh?: boolean,
    queryId?: string,
    legacyUrl?: string
): Promise<NonNullable<N['response']>> {
    if (isTimeToSeeDataSessionsNode(queryNode)) {
        return query(queryNode.source)
    }

    let response: NonNullable<N['response']>
    const logParams: Record<string, any> = {}
    const startTime = performance.now()

    const hogQLInsightsLifecycleFlagEnabled = Boolean(
        featureFlagLogic.findMounted()?.values.featureFlags?.[FEATURE_FLAGS.HOGQL_INSIGHTS_LIFECYCLE]
    )
    const hogQLInsightsPathsFlagEnabled = Boolean(
        featureFlagLogic.findMounted()?.values.featureFlags?.[FEATURE_FLAGS.HOGQL_INSIGHTS_PATHS]
    )
    const hogQLInsightsRetentionFlagEnabled = Boolean(
        featureFlagLogic.findMounted()?.values.featureFlags?.[FEATURE_FLAGS.HOGQL_INSIGHTS_RETENTION]
    )
    const hogQLInsightsTrendsFlagEnabled = Boolean(
        featureFlagLogic.findMounted()?.values.featureFlags?.[FEATURE_FLAGS.HOGQL_INSIGHTS_TRENDS]
    )
    const hogQLInsightsStickinessFlagEnabled = Boolean(
        featureFlagLogic.findMounted()?.values.featureFlags?.[FEATURE_FLAGS.HOGQL_INSIGHTS_STICKINESS]
    )
    const hogQLInsightsFunnelsFlagEnabled = Boolean(
        featureFlagLogic.findMounted()?.values.featureFlags?.[FEATURE_FLAGS.HOGQL_INSIGHTS_FUNNELS]
    )
    const hogQLInsightsLiveCompareEnabled = Boolean(
        featureFlagLogic.findMounted()?.values.featureFlags?.[FEATURE_FLAGS.HOGQL_INSIGHT_LIVE_COMPARE]
    )

    async function fetchLegacyUrl(): Promise<Record<string, any>> {
        const response = await api.getResponse(legacyUrl!)
        return response.json()
    }

    async function fetchLegacyInsights(): Promise<Record<string, any>> {
        if (!isInsightQueryNode(queryNode)) {
            throw new Error('fetchLegacyInsights called with non-insight query. Should be unreachable.')
        }
        const filters = queryNodeToFilter(queryNode)
        const params = {
            ...filters,
            ...(refresh ? { refresh: true } : {}),
            client_query_id: queryId,
            session_id: currentSessionId(),
        }
        const [resp] = await legacyInsightQuery({
            filters: params,
            currentTeamId: getCurrentTeamId(),
            methodOptions,
            refresh,
        })
        response = await resp.json()
        return response
    }

    try {
        if (isPersonsNode(queryNode)) {
            response = await api.get(getPersonsEndpoint(queryNode), methodOptions)
        } else if (isTimeToSeeDataQuery(queryNode)) {
            response = await api.query(
                {
                    ...queryNode,
                    teamId: queryNode.teamId ?? getCurrentTeamId(),
                    sessionId: queryNode.sessionId ?? currentSessionId(),
                    sessionStart: queryNode.sessionStart ?? now().subtract(1, 'day').toISOString(),
                    sessionEnd: queryNode.sessionEnd ?? now().toISOString(),
                },
                methodOptions
            )
        } else if (isInsightQueryNode(queryNode) || (isActorsQuery(queryNode) && !!legacyUrl)) {
            if (
                (hogQLInsightsLifecycleFlagEnabled && isLifecycleQuery(queryNode)) ||
                (hogQLInsightsPathsFlagEnabled &&
                    (isPathsQuery(queryNode) || (isActorsQuery(queryNode) && !!legacyUrl))) ||
                (hogQLInsightsRetentionFlagEnabled && isRetentionQuery(queryNode)) ||
                (hogQLInsightsTrendsFlagEnabled && isTrendsQuery(queryNode)) ||
                (hogQLInsightsStickinessFlagEnabled && isStickinessQuery(queryNode)) ||
                (hogQLInsightsFunnelsFlagEnabled && isFunnelsQuery(queryNode))
            ) {
                if (hogQLInsightsLiveCompareEnabled) {
                    const legacyFunction = legacyUrl ? fetchLegacyUrl : fetchLegacyInsights
                    let legacyResponse: any
                    ;[response, legacyResponse] = await Promise.all([
                        executeQuery(queryNode, methodOptions, refresh, queryId),
                        legacyFunction(),
                    ])

                    let res1 = response?.result || response?.results
                    let res2 = legacyResponse?.result || legacyResponse?.results

                    if (isLifecycleQuery(queryNode)) {
                        // Results don't come back in a predetermined order for the legacy lifecycle insight
                        const order = { new: 1, returning: 2, resurrecting: 3, dormant: 4 }
                        res1.sort((a: any, b: any) => order[a.status] - order[b.status])
                        res2.sort((a: any, b: any) => order[a.status] - order[b.status])
                    } else if (isTrendsQuery(queryNode) || isStickinessQuery(queryNode)) {
                        res1 = res1?.map((n: any) => ({
                            ...n,
                            filter: undefined,
                            action: undefined,
                            persons: undefined,
                        }))
                        res2 = res2?.map((n: any) => ({
                            ...n,
                            filter: undefined,
                            action: undefined,
                            persons: undefined,
                        }))
                    } else if (res2.length > 0 && res2[0].people) {
                        res2 = res2[0]?.people.map((n: any) => n.id)
                        res1 = res1.map((n: any) => n[0].id)
                        // Sort, since the order of the results is not guaranteed
                        res1.sort()
                        res2.sort()
                    }

                    const getTimingDiff = (): undefined | { diff: number; legacy: number; hogql: number } => {
                        const hogQLTimings = response?.timings
                        const legacyTimings = legacyResponse?.timings

                        if (!hogQLTimings || !legacyTimings) {
                            return undefined
                        }

                        const hogqlTotalTime =
                            hogQLTimings.find((n: { k: string; t: number }) => n['k'] === '.')?.t ?? 0
                        const legacyTotalTime =
                            legacyTimings.find((n: { k: string; t: number }) => n['k'] === '.')?.t ?? 0

                        return {
                            diff: hogqlTotalTime - legacyTotalTime,
                            legacy: legacyTotalTime,
                            hogql: hogqlTotalTime,
                        }
                    }

                    const almostEqual = (n1: number, n2: number, epsilon: number = 1.0): boolean =>
                        Math.abs(n1 - n2) < epsilon

                    const timingDiff = getTimingDiff()

                    const results = flattenObject(res1)
                    const legacyResults = flattenObject(res2)
                    const sortedKeys = Array.from(new Set([...Object.keys(results), ...Object.keys(legacyResults)]))
                        .filter((key) => !key.includes('.persons_urls.') && !key.includes('.people_url'))
                        .sort()
                    const tableData: any[] = [['', 'key', 'HOGQL', 'LEGACY']]
                    let matchCount = 0
                    let mismatchCount = 0
                    for (const key of sortedKeys) {
                        let isMatch = false
                        if (
                            results[key] === legacyResults[key] ||
                            (key.includes('average_conversion_time') && almostEqual(results[key], legacyResults[key]))
                        ) {
                            isMatch = true
                        }

                        if (isMatch) {
                            matchCount++
                        } else {
                            mismatchCount++
                        }

                        tableData.push([isMatch ? '✅' : '🚨', key, results[key], legacyResults[key]])
                    }

                    if (timingDiff) {
                        tableData.push([
                            timingDiff.diff <= 0 ? '🚀' : '🐌',
                            'timingDiff',
                            timingDiff.hogql,
                            timingDiff.legacy,
                        ])
                    }

                    const symbols = mismatchCount === 0 ? '🍀🍀🍀' : '🏎️🏎️🏎'
                    // eslint-disable-next-line no-console
                    console.log(`${symbols} Insight Race ${symbols}`, {
                        query: queryNode,
                        duration: performance.now() - startTime,
                        hogqlResults: results,
                        legacyResults: legacyResults,
                        equal: mismatchCount === 0,
                        response,
                        legacyResponse,
                        timingDiff,
                    })
                    const resultsLabel = mismatchCount === 0 ? '👏' : '⚠️'
                    const alertLabel = mismatchCount > 0 ? `🚨${mismatchCount}` : ''
                    // eslint-disable-next-line no-console
                    console.groupCollapsed(`Results: ${resultsLabel} ✅${matchCount} ${alertLabel} ${queryNode.kind}`)
                    // eslint-disable-next-line no-console
                    console.table(tableData)
                    // eslint-disable-next-line no-console
                    console.groupEnd()

                    posthog.capture('hogql_compare', {
                        query: queryNode,
                        equal: mismatchCount === 0,
                        mismatch_count: mismatchCount,
                        ...(timingDiff
                            ? {
                                  timing_diff: timingDiff.diff,
                                  timing_hogqL: timingDiff.hogql,
                                  timing_legacy: timingDiff.legacy,
                              }
                            : {}),
                    })
                } else {
                    response = await executeQuery(queryNode, methodOptions, refresh, queryId)
                }
            } else {
                response = await fetchLegacyInsights()
            }
        } else {
            response = await executeQuery(queryNode, methodOptions, refresh, queryId)
            if (isHogQLQuery(queryNode) && response && typeof response === 'object') {
                logParams.clickhouse_sql = (response as HogQLQueryResponse)?.clickhouse
            }
        }
        posthog.capture('query completed', { query: queryNode, duration: performance.now() - startTime, ...logParams })
        return response
    } catch (e) {
        posthog.capture('query failed', { query: queryNode, duration: performance.now() - startTime, ...logParams })
        throw e
    }
}

export function getPersonsEndpoint(query: PersonsNode): string {
    const params = {
        properties: [...(query.fixedProperties || []), ...(query.properties || [])],
        ...(query.search ? { search: query.search } : {}),
        ...(query.distinctId ? { distinct_id: query.distinctId } : {}),
        ...(query.limit ? { limit: query.limit } : {}),
        ...(query.offset ? { offset: query.offset } : {}),
    }
    if (query.cohort) {
        return api.cohorts.determineListUrl(query.cohort, params)
    }
    return api.persons.determineListUrl(params)
}

interface LegacyInsightQueryParams {
    filters: AnyPartialFilterType
    currentTeamId: number
    methodOptions?: ApiMethodOptions
    refresh?: boolean
}

export function legacyInsightQueryURL({ filters, currentTeamId, refresh }: LegacyInsightQueryParams): string {
    if (isTrendsFilter(filters) || isStickinessFilter(filters) || isLifecycleFilter(filters)) {
        return `api/projects/${currentTeamId}/insights/trend/?${toParams(filterTrendsClientSideParams(filters))}${
            refresh ? '&refresh=true' : ''
        }`
    } else if (isRetentionFilter(filters)) {
        return `api/projects/${currentTeamId}/insights/retention/?${toParams(filters)}${refresh ? '&refresh=true' : ''}`
    } else if (isFunnelsFilter(filters)) {
        return `api/projects/${currentTeamId}/insights/funnel/${refresh ? '?refresh=true' : ''}`
    } else if (isPathsFilter(filters)) {
        return `api/projects/${currentTeamId}/insights/path${refresh ? '?refresh=true' : ''}`
    } else {
        throw new Error(`Unsupported insight type: ${filters.insight}`)
    }
}

export function legacyInsightQueryExportContext({
    filters,
    currentTeamId,
    refresh,
}: LegacyInsightQueryParams): OnlineExportContext {
    const apiUrl = legacyInsightQueryURL({ filters, currentTeamId, refresh })

    if (isTrendsFilter(filters) || isStickinessFilter(filters) || isLifecycleFilter(filters)) {
        return {
            path: apiUrl,
            method: 'GET',
        }
    } else if (isRetentionFilter(filters)) {
        return {
            path: apiUrl,
            method: 'GET',
        }
    } else if (isFunnelsFilter(filters)) {
        return {
            path: apiUrl,
            method: 'POST',
            body: filters,
        }
    } else if (isPathsFilter(filters)) {
        return {
            path: apiUrl,
            method: 'POST',
            body: filters,
        }
    } else {
        throw new Error(`Unsupported insight type: ${filters.insight}`)
    }
}

export async function legacyInsightQuery({
    filters,
    currentTeamId,
    methodOptions,
    refresh,
}: LegacyInsightQueryParams): Promise<[Response, string]> {
    const apiUrl = legacyInsightQueryURL({ filters, currentTeamId, refresh })
    let fetchResponse: Response
    if (isTrendsFilter(filters) || isStickinessFilter(filters) || isLifecycleFilter(filters)) {
        fetchResponse = await api.getResponse(apiUrl, methodOptions)
    } else if (isRetentionFilter(filters)) {
        fetchResponse = await api.getResponse(apiUrl, methodOptions)
    } else if (isFunnelsFilter(filters)) {
        fetchResponse = await api.createResponse(apiUrl, filters, methodOptions)
    } else if (isPathsFilter(filters)) {
        fetchResponse = await api.createResponse(apiUrl, filters, methodOptions)
    } else {
        throw new Error(`Unsupported insight type: ${filters.insight}`)
    }
    return [fetchResponse, apiUrl]
}

export async function hogqlQuery(queryString: string, values?: Record<string, any>): Promise<HogQLQueryResponse> {
    return await query<HogQLQuery>({
        kind: NodeKind.HogQLQuery,
        query: queryString,
        values,
    })
}
