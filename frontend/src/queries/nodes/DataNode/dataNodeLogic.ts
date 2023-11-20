import { dayjs } from 'lib/dayjs'
import {
    kea,
    path,
    props,
    key,
    afterMount,
    selectors,
    propsChanged,
    reducers,
    actions,
    beforeUnmount,
    listeners,
    connect,
} from 'kea'
import { loaders } from 'kea-loaders'
import type { dataNodeLogicType } from './dataNodeLogicType'
import {
    AnyResponseType,
    DataNode,
    EventsQuery,
    EventsQueryResponse,
    PersonsNode,
    PersonsQuery,
    PersonsQueryResponse,
    QueryResponse,
    QueryTiming,
} from '~/queries/schema'
import { query } from '~/queries/query'
import {
    isInsightQueryNode,
    isEventsQuery,
    isPersonsNode,
    isQueryWithHogQLSupport,
    isPersonsQuery,
} from '~/queries/utils'
import { subscriptions } from 'kea-subscriptions'
import { objectsEqual, shouldCancelQuery, uuid } from 'lib/utils'
import clsx from 'clsx'
import api, { ApiMethodOptions, getJSONOrThrow } from 'lib/api'
import { removeExpressionComment } from '~/queries/nodes/DataTable/utils'
import { userLogic } from 'scenes/userLogic'
import { UNSAVED_INSIGHT_MIN_REFRESH_INTERVAL_MINUTES } from 'scenes/insights/insightLogic'
import { teamLogic } from 'scenes/teamLogic'
import equal from 'fast-deep-equal'
import { filtersToQueryNode } from '../InsightQuery/utils/filtersToQueryNode'
import { compareInsightQuery } from 'scenes/insights/utils/compareInsightQuery'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export interface DataNodeLogicProps {
    key: string
    query: DataNode
    /** Cached results when fetching nodes in bulk (list endpoint), sharing or exporting. */
    cachedResults?: AnyResponseType
    /** Disabled data fetching and only allow cached results. */
    doNotLoad?: boolean
}

const AUTOLOAD_INTERVAL = 30000

const queryEqual = (a: DataNode, b: DataNode): boolean => {
    if (isInsightQueryNode(a) && isInsightQueryNode(b)) {
        return compareInsightQuery(a, b, true)
    } else {
        return objectsEqual(a, b)
    }
}

export const dataNodeLogic = kea<dataNodeLogicType>([
    path(['queries', 'nodes', 'dataNodeLogic']),
    connect({
        values: [userLogic, ['user'], teamLogic, ['currentTeamId'], featureFlagLogic, ['featureFlags']],
    }),
    props({ query: {} } as DataNodeLogicProps),
    key((props) => props.key),
    propsChanged(({ actions, props }, oldProps) => {
        if (!props.query) {
            return // Can't do anything without a query
        }
        if (oldProps.query && props.query.kind !== oldProps.query.kind) {
            actions.clearResponse()
        }
        if (!queryEqual(props.query, oldProps.query)) {
            if (
                !props.cachedResults ||
                (isInsightQueryNode(props.query) && !props.cachedResults['result'] && !props.cachedResults['results'])
            ) {
                actions.loadData()
            } else {
                actions.setResponse(props.cachedResults)
            }
        }
    }),
    actions({
        loadData: (refresh = false) => ({ refresh, queryId: uuid() }),
        abortAnyRunningQuery: true,
        abortQuery: (payload: { queryId: string }) => payload,
        cancelQuery: true,
        setResponse: (response: Exclude<AnyResponseType, undefined>) => response,
        clearResponse: true,
        startAutoLoad: true,
        stopAutoLoad: true,
        toggleAutoLoad: true,
        highlightRows: (rows: any[]) => ({ rows }),
        setElapsedTime: (elapsedTime: number) => ({ elapsedTime }),
    }),
    loaders(({ actions, cache, values, props }) => ({
        response: [
            props.cachedResults ?? null,
            {
                setResponse: (response) => response,
                clearResponse: () => null,
                loadData: async ({ refresh, queryId }, breakpoint) => {
                    if (props.doNotLoad) {
                        return props.cachedResults
                    }
                    if (
                        isInsightQueryNode(props.query) &&
                        !(values.hogQLInsightsFlagEnabled && isQueryWithHogQLSupport(props.query)) &&
                        props.cachedResults &&
                        props.cachedResults['id'] &&
                        props.cachedResults['filters'] &&
                        equal(props.query, filtersToQueryNode(props.cachedResults['filters']))
                    ) {
                        const url = `api/projects/${values.currentTeamId}/insights/${props.cachedResults['id']}?refresh=true`
                        const fetchResponse = await api.getResponse(url)
                        const data = await getJSONOrThrow(fetchResponse)
                        breakpoint()
                        return data
                    }

                    if (props.cachedResults && !refresh) {
                        if (
                            props.cachedResults['result'] ||
                            props.cachedResults['results'] ||
                            !isInsightQueryNode(props.query)
                        ) {
                            return props.cachedResults
                        }
                    }

                    if (!values.currentTeamId) {
                        // if shared/exported, the team is not loaded
                        return null
                    }

                    if (props.query === undefined || Object.keys(props.query).length === 0) {
                        // no need to try and load a query before properly initialized
                        return null
                    }

                    actions.abortAnyRunningQuery()
                    cache.abortController = new AbortController()
                    const methodOptions: ApiMethodOptions = {
                        signal: cache.abortController.signal,
                    }
                    const now = performance.now()
                    try {
                        const data = (await query<DataNode>(props.query, methodOptions, refresh, queryId)) ?? null
                        breakpoint()
                        actions.setElapsedTime(performance.now() - now)
                        return data
                    } catch (e: any) {
                        actions.setElapsedTime(performance.now() - now)
                        if (shouldCancelQuery(e)) {
                            actions.abortQuery({ queryId })
                        }
                        breakpoint()
                        e.queryId = queryId
                        throw e
                    }
                },
                loadNewData: async () => {
                    if (props.cachedResults) {
                        return props.cachedResults
                    }

                    if (!values.canLoadNewData || values.dataLoading) {
                        return values.response
                    }
                    if (isEventsQuery(props.query) && values.newQuery) {
                        const now = performance.now()
                        const newResponse = (await query(values.newQuery)) ?? null
                        actions.setElapsedTime(performance.now() - now)
                        if (newResponse?.results) {
                            actions.highlightRows(newResponse?.results)
                        }
                        const currentResults = ((values.response || { results: [] }) as EventsQueryResponse).results
                        return {
                            ...values.response,
                            results: [...(newResponse?.results ?? []), ...currentResults],
                        }
                    }
                    return values.response
                },
                loadNextData: async () => {
                    if (props.cachedResults) {
                        return props.cachedResults
                    }

                    if (!values.canLoadNextData || values.dataLoading || !values.nextQuery) {
                        return values.response
                    }
                    // TODO: unify when we use the same backend endpoint for both
                    const now = performance.now()
                    if (isEventsQuery(props.query) || isPersonsQuery(props.query)) {
                        const newResponse = (await query(values.nextQuery)) ?? null
                        actions.setElapsedTime(performance.now() - now)
                        const queryResponse = values.response as QueryResponse
                        return {
                            ...queryResponse,
                            results: [...(queryResponse?.results ?? []), ...(newResponse?.results ?? [])],
                            hasMore: newResponse?.hasMore,
                        }
                    } else if (isPersonsNode(props.query)) {
                        const newResponse = (await query(values.nextQuery)) ?? null
                        actions.setElapsedTime(performance.now() - now)
                        if (Array.isArray(values.response)) {
                            // help typescript by asserting we can't have an array here
                            throw new Error('Unexpected response type for persons node query')
                        }
                        return {
                            ...values.response,
                            results: [...(values.response?.results ?? []), ...(newResponse?.results ?? [])],
                            next: newResponse?.next,
                        }
                    }
                    return values.response
                },
            },
        ],
    })),
    reducers(({ props }) => ({
        dataLoading: [
            false,
            {
                loadData: () => true,
                loadDataSuccess: () => false,
                loadDataFailure: () => false,
            },
        ],
        newDataLoading: [
            false,
            {
                loadNewData: () => true,
                loadNewDataSuccess: () => false,
                loadNewDataFailure: () => false,
            },
        ],
        nextDataLoading: [
            false,
            {
                loadNextData: () => true,
                loadNextDataSuccess: () => false,
                loadNextDataFailure: () => false,
            },
        ],
        queryCancelled: [
            false,
            {
                loadNextData: () => false,
                loadNewData: () => false,
                loadData: () => false,
                cancelQuery: () => true,
            },
        ],
        autoLoadToggled: [
            false,
            // store the 'autoload toggle' state in localstorage, separately for each data node kind
            {
                persist: true,
                storageKey: clsx('queries.nodes.dataNodeLogic.autoLoadToggled', props.query?.kind, {
                    action: isEventsQuery(props.query) && props.query.actionId,
                    person: isEventsQuery(props.query) && props.query.personId,
                }),
            },
            { toggleAutoLoad: (state) => !state },
        ],
        autoLoadStarted: [false, { startAutoLoad: () => true, stopAutoLoad: () => false }],
        highlightedRows: [
            new Set<any>(),
            {
                highlightRows: (state, { rows }) => new Set([...Array.from(state), ...rows]),
                loadDataSuccess: () => new Set(),
            },
        ],
        loadingStart: [
            null as number | null,
            {
                setElapsedTime: () => null,
                loadData: () => performance.now(),
                loadNewData: () => performance.now(),
                loadNextData: () => performance.now(),
            },
        ],
        response: {
            // Clear the response if a failure to avoid showing inconsistencies in the UI
            loadDataFailure: () => null,
        },
        responseErrorObject: [
            null as Record<string, any> | null,
            {
                loadData: () => null,
                loadDataFailure: (_, { errorObject }) => errorObject,
                loadDataSuccess: () => null,
            },
        ],
        responseError: [
            null as string | null,
            {
                loadData: () => null,
                loadDataFailure: (_, { error, errorObject }) => {
                    if (errorObject && 'error' in errorObject) {
                        return errorObject.error
                    }
                    if (errorObject && 'detail' in errorObject) {
                        return errorObject.detail
                    }
                    return error ?? 'Error loading data'
                },
                loadDataSuccess: () => null,
            },
        ],
        elapsedTime: [
            null as number | null,
            {
                setElapsedTime: (_, { elapsedTime }) => elapsedTime,
                loadData: () => null,
                loadNewData: () => null,
                loadNextData: () => null,
            },
        ],
    })),
    selectors({
        isShowingCachedResults: [
            () => [(_, props) => props.cachedResults ?? null],
            (cachedResults: AnyResponseType | null): boolean => !!cachedResults,
        ],
        hogQLInsightsFlagEnabled: [
            (s) => [s.featureFlags],
            (featureFlags) => featureFlags[FEATURE_FLAGS.HOGQL_INSIGHTS],
        ],
        query: [(_, p) => [p.query], (query) => query],
        newQuery: [
            (s, p) => [p.query, s.response],
            (query, response): DataNode | null => {
                if (!isEventsQuery(query)) {
                    return null
                }
                if (isEventsQuery(query) && !query.before) {
                    const sortKey = query.orderBy?.[0] ?? 'timestamp DESC'
                    if (sortKey === 'timestamp DESC') {
                        const sortColumnIndex = query.select
                            .map((hql) => removeExpressionComment(hql))
                            .indexOf('timestamp')
                        if (sortColumnIndex !== -1) {
                            const typedResults = (response as EventsQuery['response'])?.results
                            const firstTimestamp = typedResults?.[0]?.[sortColumnIndex]
                            if (firstTimestamp) {
                                const nextQuery: EventsQuery = { ...query, after: firstTimestamp }
                                return nextQuery
                            } else {
                                return query
                            }
                        }
                    }
                }
                return null
            },
        ],
        canLoadNewData: [
            (s) => [s.newQuery, s.isShowingCachedResults],
            (newQuery, isShowingCachedResults) => (isShowingCachedResults ? false : !!newQuery),
        ],
        nextQuery: [
            (s, p) => [p.query, s.response, s.responseError, s.dataLoading, s.isShowingCachedResults],
            (query, response, responseError, dataLoading, isShowingCachedResults): DataNode | null => {
                if (isShowingCachedResults) {
                    return null
                }

                if ((isEventsQuery(query) || isPersonsQuery(query)) && !responseError && !dataLoading) {
                    if ((response as EventsQueryResponse | PersonsQueryResponse)?.hasMore) {
                        const sortKey = query.orderBy?.[0] ?? 'timestamp DESC'
                        const typedResults = (response as QueryResponse)?.results
                        if (isEventsQuery(query) && sortKey === 'timestamp DESC') {
                            const sortColumnIndex = query.select
                                .map((hql) => removeExpressionComment(hql))
                                .indexOf('timestamp')
                            if (sortColumnIndex !== -1) {
                                const lastTimestamp = typedResults?.[typedResults.length - 1]?.[sortColumnIndex]
                                if (lastTimestamp) {
                                    const newQuery: EventsQuery = { ...query, before: lastTimestamp }
                                    return newQuery
                                }
                            }
                        } else {
                            return {
                                ...query,
                                offset: typedResults?.length || 0,
                            } as EventsQuery | PersonsQuery
                        }
                    }
                }
                if (isPersonsNode(query) && response && !responseError && response.next) {
                    const personsResults = (response as PersonsNode['response'])?.results
                    const nextQuery: PersonsNode = {
                        ...query,
                        limit: query.limit || 100,
                        offset: personsResults.length,
                    }
                    return nextQuery
                }
                return null
            },
        ],
        canLoadNextData: [
            (s) => [s.nextQuery, s.isShowingCachedResults],
            (nextQuery, isShowingCachedResults) => (isShowingCachedResults ? false : !!nextQuery),
        ],
        autoLoadRunning: [
            (s) => [s.autoLoadToggled, s.autoLoadStarted, s.dataLoading],
            (autoLoadToggled, autoLoadStarted, dataLoading) => autoLoadToggled && autoLoadStarted && !dataLoading,
        ],
        lastRefresh: [
            (s) => [s.response],
            (response): string | null => {
                return response && 'last_refresh' in response ? response.last_refresh : null
            },
        ],
        nextAllowedRefresh: [
            (s, p) => [p.query, s.response],
            (query, response): string | null => {
                return isInsightQueryNode(query) && response && 'next_allowed_client_refresh' in response
                    ? response.next_allowed_client_refresh
                    : null
            },
        ],
        getInsightRefreshButtonDisabledReason: [
            (s) => [s.nextAllowedRefresh, s.lastRefresh],
            (nextAllowedRefresh: string | null, lastRefresh: string | null) => (): string => {
                const now = dayjs()
                let disabledReason = ''
                if (!!nextAllowedRefresh && now.isBefore(dayjs(nextAllowedRefresh))) {
                    // If this is a saved insight, the result will contain nextAllowedRefresh, and we use that to disable the button
                    disabledReason = `You can refresh this insight again ${dayjs(nextAllowedRefresh).from(now)}`
                } else if (
                    !!lastRefresh &&
                    now.subtract(UNSAVED_INSIGHT_MIN_REFRESH_INTERVAL_MINUTES - 0.5, 'minutes').isBefore(lastRefresh)
                ) {
                    // Unsaved insights don't get cached and get refreshed on every page load, but we avoid allowing users to click
                    // 'refresh' more than once every UNSAVED_INSIGHT_MIN_REFRESH_INTERVAL_MINUTES. This can be bypassed by simply
                    // refreshing the page though, as there's no cache layer on the backend
                    disabledReason = `You can refresh this insight again ${dayjs(lastRefresh)
                        .add(UNSAVED_INSIGHT_MIN_REFRESH_INTERVAL_MINUTES, 'minutes')
                        .from(now)}`
                }

                return disabledReason
            },
        ],
        timings: [
            (s) => [s.response],
            (response): QueryTiming[] | null => {
                return response && 'timings' in response ? response.timings : null
            },
        ],
    }),
    listeners(({ actions, values, cache }) => ({
        abortAnyRunningQuery: () => {
            if (cache.abortController) {
                cache.abortController.abort()
                cache.abortController = null
            }
        },
        abortQuery: async ({ queryId }) => {
            try {
                const { currentTeamId } = values
                await api.delete(`api/projects/${currentTeamId}/query/${queryId}/`)
            } catch (e) {
                console.warn('Failed cancelling query', e)
            }
        },
        cancelQuery: () => {
            actions.abortAnyRunningQuery()
        },
    })),
    subscriptions(({ actions, cache, values }) => ({
        autoLoadRunning: (autoLoadRunning) => {
            if (cache.autoLoadInterval) {
                window.clearInterval(cache.autoLoadInterval)
                cache.autoLoadInterval = null
            }
            if (autoLoadRunning) {
                actions.loadNewData()
                cache.autoLoadInterval = window.setInterval(() => {
                    if (!values.responseLoading) {
                        actions.loadNewData()
                    }
                }, AUTOLOAD_INTERVAL)
            }
        },
    })),
    afterMount(({ actions, props }) => {
        if (Object.keys(props.query || {}).length > 0) {
            actions.loadData()
        }
    }),
    beforeUnmount(({ actions, values }) => {
        if (values.autoLoadRunning) {
            actions.stopAutoLoad()
        }
        if (values.dataLoading) {
            actions.abortAnyRunningQuery()
        }
    }),
])
