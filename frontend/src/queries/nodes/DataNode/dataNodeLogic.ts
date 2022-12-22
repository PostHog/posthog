import { kea, path, props, key, afterMount, selectors, propsChanged, reducers, actions, beforeUnmount } from 'kea'
import { loaders } from 'kea-loaders'
import type { dataNodeLogicType } from './dataNodeLogicType'
import { DataNode, EventsQuery, PersonsNode } from '~/queries/schema'
import { query } from '~/queries/query'
import { isEventsQuery, isPersonsNode } from '~/queries/utils'
import { subscriptions } from 'kea-subscriptions'
import { objectsEqual } from 'lib/utils'
import clsx from 'clsx'
import { getNewQuery, getNextQuery } from '~/queries/nodes/DataNode/utils'
import { ApiMethodOptions } from 'lib/api'

export interface DataNodeLogicProps {
    key: string
    query: DataNode
}

const AUTOLOAD_INTERVAL = 5000

export const dataNodeLogic = kea<dataNodeLogicType>([
    path(['queries', 'nodes', 'dataNodeLogic']),
    props({} as DataNodeLogicProps),
    key((props) => props.key),
    propsChanged(({ actions, props }, oldProps) => {
        if (!objectsEqual(props.query, oldProps.query)) {
            actions.loadData()
        }
    }),
    actions({
        loadData: true,
        startAutoLoad: true,
        stopAutoLoad: true,
        toggleAutoLoad: true,
        highlightRows: (rows: any[]) => ({ rows }),
        setElapsedTime: (elapsedTime: number) => ({ elapsedTime }),
    }),
    loaders(({ actions, cache, values, props }) => ({
        response: [
            null as DataNode['response'] | null,
            {
                loadData: async (_, breakpoint) => {
                    if (cache.abortController) {
                        cache.abortController.abort()
                    }
                    cache.abortController = new AbortController()
                    const methodOptions: ApiMethodOptions = {
                        signal: cache.abortController.signal,
                    }
                    try {
                        const now = performance.now()
                        const data = (await query<DataNode>(props.query, methodOptions)) ?? null
                        breakpoint()
                        actions.setElapsedTime(performance.now() - now)
                        return data
                    } catch (e: any) {
                        cache.abortController = null
                        if (e.name === 'AbortError' || e.message?.name === 'AbortError') {
                            return values.response
                        } else {
                            throw e
                        }
                    }
                },
                loadNewData: async () => {
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
                        return {
                            ...values.response,
                            results: [...(newResponse?.results ?? []), ...(values.response?.results ?? [])],
                        }
                    }
                    return values.response
                },
                loadNextData: async () => {
                    if (!values.canLoadNextData || values.dataLoading || !values.nextQuery) {
                        return values.response
                    }
                    // TODO: unify when we use the same backend endpoint for both
                    const now = performance.now()
                    if (isEventsQuery(props.query)) {
                        const newResponse = (await query(values.nextQuery)) ?? null
                        actions.setElapsedTime(performance.now() - now)
                        return {
                            ...values.response,
                            results: [...(values.response?.results ?? []), ...(newResponse?.results ?? [])],
                            hasMore: newResponse?.hasMore,
                        }
                    } else if (isPersonsNode(props.query)) {
                        const newResponse = (await query(values.nextQuery)) ?? null
                        actions.setElapsedTime(performance.now() - now)
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
        dataLoading: [false, { loadData: () => true, loadDataSuccess: () => false, loadDataFailure: () => false }],
        newDataLoading: [
            false,
            { loadNewData: () => true, loadNewDataSuccess: () => false, loadNewDataFailure: () => false },
        ],
        nextDataLoading: [
            false,
            { loadNextData: () => true, loadNextDataSuccess: () => false, loadNextDataFailure: () => false },
        ],
        autoLoadToggled: [
            false,
            // store the autoload toggle's state in localstorage, separately for each data node kind
            {
                persist: true,
                storageKey: clsx('queries.nodes.dataNodeLogic.autoLoadToggled', props.query.kind, {
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
        newQuery: [
            (s, p) => [p.query, s.response],
            (query, response): DataNode | null => {
                return isEventsQuery(query) && query.orderBy?.length === 1 && query.orderBy[0] === '-timestamp'
                    ? getNewQuery({ ...query, response: response as EventsQuery['response'] })
                    : null
            },
        ],
        canLoadNewData: [(s) => [s.newQuery], (newQuery) => !!newQuery],
        nextQuery: [
            (s, p) => [p.query, s.response],
            (query, response): DataNode | null => {
                if (isEventsQuery(query)) {
                    if ((response as EventsQuery['response'])?.hasMore) {
                        return getNextQuery({ ...query, response: response as EventsQuery['response'] })
                    }
                }
                if (isPersonsNode(query) && response) {
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
        canLoadNextData: [(s) => [s.nextQuery], (nextQuery) => !!nextQuery],
        autoLoadRunning: [
            (s) => [s.autoLoadToggled, s.autoLoadStarted, s.dataLoading],
            (autoLoadToggled, autoLoadStarted, dataLoading) => autoLoadToggled && autoLoadStarted && !dataLoading,
        ],
    }),
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
    afterMount(({ actions }) => {
        actions.loadData()
    }),
    beforeUnmount(({ actions, values }) => {
        if (values.autoLoadRunning) {
            actions.stopAutoLoad()
        }
    }),
])
