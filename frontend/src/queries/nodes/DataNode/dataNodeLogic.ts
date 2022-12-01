import { kea, path, props, key, afterMount, selectors, propsChanged, reducers, actions, beforeUnmount } from 'kea'
import { loaders } from 'kea-loaders'
import type { dataNodeLogicType } from './dataNodeLogicType'
import { DataNode, EventsNode } from '~/queries/schema'
import { query } from '~/queries/query'
import { isEventsNode } from '~/queries/utils'
import { subscriptions } from 'kea-subscriptions'

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
        if (JSON.stringify(props.query) !== JSON.stringify(oldProps.query)) {
            actions.loadData()
        }
    }),
    actions({
        startAutoLoad: true,
        stopAutoLoad: true,
        toggleAutoLoad: true,
    }),
    loaders(({ values }) => ({
        response: [
            null as DataNode['response'] | null,
            {
                loadData: async () => {
                    return (await query<DataNode>(values.query)) ?? null
                },
                loadNewData: async () => {
                    if (!values.canLoadNewData) {
                        return
                    }
                    const oldResponse = values.response as EventsNode['response'] | null
                    const diffQuery: EventsNode =
                        oldResponse && oldResponse.results?.length > 0
                            ? {
                                  ...values.query,
                                  after: oldResponse.results[0].timestamp,
                              }
                            : values.query
                    const newResponse = (await query(diffQuery)) ?? null
                    return {
                        results: [...(newResponse?.results ?? []), ...(oldResponse?.results ?? [])],
                        next: oldResponse?.next,
                    }
                },
                loadNextData: async () => {
                    if (!values.canLoadNextData) {
                        return
                    }
                    const oldResponse = values.response as EventsNode['response'] | null
                    const diffQuery: EventsNode =
                        oldResponse && oldResponse.results?.length > 0
                            ? {
                                  ...values.query,
                                  before: oldResponse.results[oldResponse.results.length - 1].timestamp,
                              }
                            : values.query
                    const newResponse = (await query(diffQuery)) ?? null
                    return {
                        results: [...(oldResponse?.results ?? []), ...(newResponse?.results ?? [])],
                        next: oldResponse?.next,
                    }
                },
            },
        ],
    })),
    reducers({
        newDataLoading: [
            false,
            { loadNewData: () => true, loadNewDataSuccess: () => false, loadDataFailure: () => false },
        ],
        nextDataLoading: [
            false,
            { loadNextData: () => true, loadNextDataSuccess: () => false, loadNextDataFailure: () => false },
        ],
        autoLoadEnabled: [false, { toggleAutoLoad: (state) => !state }],
        autoLoadStarted: [false, { startAutoLoad: () => true, stopAutoLoad: () => false }],
    }),
    selectors({
        query: [() => [(_, props) => props.query], (query) => query],
        canLoadNewData: [
            (s) => [s.query],
            (query) => {
                return isEventsNode(query)
            },
        ],
        canLoadNextData: [
            (s) => [s.query, s.response],
            (query, response) => {
                return (
                    isEventsNode(query) &&
                    (response as EventsNode['response'])?.next &&
                    ((response as EventsNode['response'])?.results?.length ?? 0) > 0
                )
            },
        ],
        autoLoadRunning: [
            (s) => [s.autoLoadEnabled, s.autoLoadStarted],
            (autoLoadEnabled, autoLoadStarted) => autoLoadEnabled && autoLoadStarted,
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
