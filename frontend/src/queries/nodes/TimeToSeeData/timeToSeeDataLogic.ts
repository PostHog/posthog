import { kea, props, key, afterMount, path } from 'kea'
import { loaders } from 'kea-loaders'
import { DataNode, TimeToSeeDataQuery } from '~/queries/schema'
import { query } from '~/queries/query'
import { TimeToSeeNode } from './types'

import type { timeToSeeDataLogicType } from './timeToSeeDataLogicType'

export interface TimeToSeeDataLogicProps {
    key: string
    query: TimeToSeeDataQuery
}

export const timeToSeeDataLogic = kea<timeToSeeDataLogicType>([
    path(['queries', 'nodes', 'TimeToSeeData', 'timeToSeeDataLogic']),
    props({} as TimeToSeeDataLogicProps),
    key((props) => props.key),
    loaders(({ props }) => ({
        response: [
            null as TimeToSeeNode | null,
            {
                loadData: async () => {
                    // TODO: Resolve this mess
                    return (await query<TimeToSeeNode>(props.query)) ?? null
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadData()
    }),
])
