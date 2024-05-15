import { connect, kea, path, props, selectors } from 'kea'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { LogsQuery, LogsQueryResult } from '~/queries/schema'

import type { logsDataLogicType } from './logsDataLogicType'

export interface LogsDataLogicProps {
    key: string
    query: LogsQuery
}

export const logsDataLogic = kea<logsDataLogicType>([
    path(['scenes', 'logs', 'logsSceneLogic']),
    props({ query: {} } as LogsDataLogicProps),
    connect((props: LogsDataLogicProps) => ({
        values: [
            dataNodeLogic({
                key: props.key,
                query: props.query,
            }),
            ['response', 'responseLoading', 'query'],
        ],
    })),
    selectors({
        data: [
            (s) => [s.response],
            (response): LogsQueryResult[] => {
                return response?.results ?? []
            },
        ],
        sparklineData: [
            (s) => [s.data],
            (data) => {
                const results: Record<string, number> = {}
                data.forEach((log) => {
                    const toStartOfMinute = new Date(log.timestamp)
                    toStartOfMinute.setSeconds(0)
                    toStartOfMinute.setMilliseconds(0)
                    results[toStartOfMinute.toISOString()] = (results[toStartOfMinute.toISOString()] || 0) + 1
                })
                return {
                    labels: Object.keys(results),
                    data: Object.values(results),
                }
            },
        ],
    }),
])
