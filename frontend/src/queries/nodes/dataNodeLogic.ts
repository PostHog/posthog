import { kea, path, props, key, afterMount, selectors, propsChanged } from 'kea'
import { loaders } from 'kea-loaders'
import type { dataNodeLogicType } from './dataNodeLogicType'
import { DataNode, EventsNode } from '~/queries/schema'
import { query } from '~/queries/query'
import { isEventsNode } from '~/queries/utils'

export interface DataNodeLogicProps {
    key: string
    query: DataNode
}

export const dataNodeLogic = kea<dataNodeLogicType>([
    path(['queries', 'nodes', 'dataNodeLogic']),
    props({} as DataNodeLogicProps),
    key((props) => props.key),
    propsChanged(({ actions, props }, oldProps) => {
        if (JSON.stringify(props.query) !== JSON.stringify(oldProps.query)) {
            actions.loadData()
        }
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
                    const response = values.response as EventsNode['response'] | null
                    const diffQuery: EventsNode =
                        response && response.results?.length > 0
                            ? {
                                  ...values.query,
                                  after: response.results[0].timestamp,
                              }
                            : values.query
                    const results = (await query(diffQuery)) ?? null
                    return {
                        results: [...(results?.results ?? []), ...(response?.results ?? [])],
                    }
                },
                loadNextData: async () => {
                    if (!values.canLoadNewData) {
                        return
                    }
                    const response = values.response as EventsNode['response'] | null
                    const diffQuery: EventsNode =
                        response && response.results?.length > 0
                            ? {
                                  ...values.query,
                                  before: response.results[response.results.length - 1].timestamp,
                              }
                            : values.query
                    const results = (await query(diffQuery)) ?? null
                    return {
                        results: [...(response?.results ?? []), ...(results?.results ?? [])],
                        next: response?.next,
                    }
                },
            },
        ],
    })),
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
                return isEventsNode(query) && response?.next
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadData()
    }),
])
