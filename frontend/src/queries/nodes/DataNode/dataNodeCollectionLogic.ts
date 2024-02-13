import { actions, kea, key, listeners, path, props, reducers } from 'kea'

import type { dataNodeCollectionLogicType } from './dataNodeCollectionLogicType'

export interface DataNodeRegisteredProps {
    id: string
    loadData: (refresh: boolean) => void
}

export interface DataNodeCollectionProps {
    key: string
}

export const dataNodeCollectionLogic = kea<dataNodeCollectionLogicType>([
    path(['queries', 'nodes', 'dataNodeCollectionLogic']),
    props({} as DataNodeCollectionProps),
    key((props: DataNodeCollectionProps) => {
        console.log('key', props.key)

        return props.key
    }),
    actions({
        mountDataNode: (id: string, props: DataNodeRegisteredProps) => ({ id, props }),
        unmountDataNode: (id: string) => ({ id }),
        reload: true,
    }),
    reducers({
        mountedDataNodes: [
            [] as DataNodeRegisteredProps[],
            {
                mountDataNode: (state, payload) => {
                    console.log('mountDataNode', payload.id, payload.props)
                    const removed = state.filter((node) => node.id !== payload.id)
                    return [...removed, payload.props]
                },
                unmountDataNode: (state, payload) => state.filter((node) => node.id !== payload.id),
            },
        ],
    }),
    listeners(({ values }) => ({
        reload: () => {
            console.log('reload', values.mountedDataNodes)
            values.mountedDataNodes.forEach((node) => node.loadData(true))
        },
    })),
])
