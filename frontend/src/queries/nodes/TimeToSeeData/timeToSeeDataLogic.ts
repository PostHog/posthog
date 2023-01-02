import { kea, props, key, afterMount, path } from 'kea'
import { loaders } from 'kea-loaders'
import { TimeToSeeDataQuery } from '~/queries/schema'
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
                    const response = await query(props.query)
                    // TODO: Resolve this typing mess
                    return (response ?? null) as any as TimeToSeeNode | null
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadData()
    }),
])
