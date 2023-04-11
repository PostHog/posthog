import { kea, props, key, path, connect, listeners, reducers, actions } from 'kea'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { DataNode } from '~/queries/schema'
import { InsightLogicProps } from '~/types'
import { keyForInsightLogicProps } from './sharedUtils'

import type { insightDataTimingLogicType } from './insightDataTimingLogicType'

export const insightDataTimingLogic = kea<insightDataTimingLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'insightDataTimingLogic', key]),
    connect((props: InsightLogicProps) => ({
        actions: [
            // TODO: need to pass empty query here, as otherwise dataNodeLogic will throw
            dataNodeLogic({ key: insightVizDataNodeKey(props), query: {} as DataNode }),
            ['loadData', 'loadDataSuccess', 'loadDataFailure'],
        ],
    })),
    actions({
        startQuery: (queryId: string) => ({ queryId }),
        endQuery: (payload: {
            queryId: string
            // view: InsightType
            // scene: Scene | null
            lastRefresh: string | null
            nextAllowedRefresh: string | null
            exception?: Record<string, any>
            response?: { cached: boolean; apiResponseBytes: number; apiUrl: string }
        }) => payload,
        abortQuery: (payload: {
            queryId: string
            // view: InsightType
            // scene: Scene | null
            exception?: Record<string, any>
        }) => payload,
    }),
    reducers({
        queryStartTimes: [
            {} as Record<string, number>,
            {
                startQuery: (state, { queryId }) => ({ ...state, [queryId]: performance.now() }),
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        loadData: ({ queryId }) => {
            console.debug('loadData', queryId)
            actions.startQuery(queryId)
        },
        loadDataSuccess: ({ payload }) => {
            const duration = performance.now() - values.queryStartTimes[payload.queryId]
            console.debug('loadDataSuccess', payload, duration)
        },
        loadDataFailure: ({ payload }) => {
            const duration = performance.now() - values.queryStartTimes[payload.queryId]
            console.debug('loadDataFailure', payload, duration)
        },
    })),
])
