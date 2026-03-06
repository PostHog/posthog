import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'

import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { InsightLogicProps } from '~/types'

import type { insightDataTimingLogicType } from './insightDataTimingLogicType'
import { keyForInsightLogicProps } from './sharedUtils'

function getQueryResourceTiming(): {
    ttfb_ms?: number
    download_ms?: number
    api_response_bytes?: number
} {
    const entries = performance.getEntriesByType('resource') as PerformanceResourceTiming[]
    for (let i = entries.length - 1; i >= 0; i--) {
        const entry = entries[i]
        if (entry.name.includes('/api/') && entry.name.includes('query') && entry.responseStart > 0) {
            return {
                ttfb_ms: Math.round(entry.responseStart - entry.requestStart),
                download_ms: Math.round(entry.responseEnd - entry.responseStart),
                api_response_bytes: entry.transferSize || undefined,
            }
        }
    }
    return {}
}

export const insightDataTimingLogic = kea<insightDataTimingLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'insightDataTimingLogic', key]),
    connect((props: InsightLogicProps) => ({
        values: [
            teamLogic,
            ['currentTeamId'],
            dataNodeLogic({ key: insightVizDataNodeKey(props) } as DataNodeLogicProps),
            ['query', 'response'],
        ],
        actions: [
            dataNodeLogic({ key: insightVizDataNodeKey(props) } as DataNodeLogicProps),
            ['loadData', 'loadDataSuccess', 'loadDataFailure', 'abortQuery as loadDataCancellation'],
        ],
        logic: [eventUsageLogic],
    })),
    actions({
        startQuery: (queryId: string) => ({ queryId }),
        removeQuery: (queryId: string) => ({ queryId }),
    }),
    reducers({
        queryStartTimes: [
            {} as Record<string, number>,
            {
                startQuery: (state, { queryId }) => ({ ...state, [queryId]: performance.now() }),
                removeQuery: (state, { queryId }) => {
                    const { [queryId]: remove, ...rest } = state
                    return rest
                },
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        loadData: ({ queryId }) => {
            actions.startQuery(queryId)
        },
        loadDataSuccess: ({ payload }) => {
            // ignore initialization
            if (!payload || !values.queryStartTimes[payload.queryId]) {
                return
            }

            const duration = performance.now() - values.queryStartTimes[payload.queryId]

            eventUsageLogic.actions.reportTimeToSeeData({
                team_id: values.currentTeamId,
                type: 'insight_load',
                context: 'insight',
                primary_interaction_id: payload.queryId,
                query_id: payload.queryId,
                status: 'success',
                time_to_see_data_ms: Math.floor(duration),
                insights_fetched: 1,
                insights_fetched_cached:
                    values.response && 'is_cached' in values.response && values.response.is_cached ? 1 : 0,
                // api_response_bytes: values.response?.apiResponseBytes, getResponseB
                // api_url: values.response?.apiUrl,
                insight: values.query.kind,
                is_primary_interaction: true,
                ...getQueryResourceTiming(),
            })

            actions.removeQuery(payload.queryId)
        },
        loadDataFailure: ({ errorObject }) => {
            // ignore unexpected errors without query id
            if (!errorObject.queryId) {
                return
            }

            const duration = performance.now() - values.queryStartTimes[errorObject.queryId]
            eventUsageLogic.actions.reportTimeToSeeData({
                team_id: values.currentTeamId,
                type: 'insight_load',
                context: 'insight',
                primary_interaction_id: errorObject.queryId,
                query_id: errorObject.queryId,
                status: 'failure',
                time_to_see_data_ms: Math.floor(duration),
                insights_fetched: 1,
                insights_fetched_cached:
                    values.response && 'is_cached' in values.response && values.response.is_cached ? 1 : 0,
                // api_response_bytes: values.response?.apiResponseBytes, getResponseB
                // api_url: values.response?.apiUrl,
                insight: values.query.kind,
                is_primary_interaction: true,
            })

            actions.removeQuery(errorObject.queryId)
        },
        loadDataCancellation: (payload) => {
            const duration = performance.now() - values.queryStartTimes[payload.queryId]
            eventUsageLogic.actions.reportTimeToSeeData({
                team_id: values.currentTeamId,
                type: 'insight_load',
                context: 'insight',
                primary_interaction_id: payload.queryId,
                query_id: payload.queryId,
                status: 'cancelled',
                time_to_see_data_ms: Math.floor(duration),
                insights_fetched: 0,
                insights_fetched_cached: 0,
                api_response_bytes: 0,
                insight: values.query.kind,
            })

            actions.removeQuery(payload.queryId)
        },
    })),
])
