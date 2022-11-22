import { kea, path, props, key, afterMount, selectors, propsChanged } from 'kea'
import { loaders } from 'kea-loaders'
import type { dataNodeLogicType } from './dataNodeLogicType'
import { DataNode } from '~/queries/schema'
import { query } from '~/queries/query'

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
    selectors({ query: [() => [(_, props) => props.query], (query) => query] }),
    loaders(({ values }) => ({
        response: [
            null as DataNode['response'] | null,
            {
                loadData: async () => {
                    console.log(values.query)
                    const response = (await query<DataNode>(values.query)) ?? null
                    return response
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadData()
    }),
])
