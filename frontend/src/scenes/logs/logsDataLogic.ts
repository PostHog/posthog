import { connect, kea, path, props, selectors } from 'kea'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { LogsQuery } from '~/queries/schema'

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
            ['response', 'responseLoading'],
        ],
    })),
    selectors({
        sparklineData: [
            (s) => [s.response],
            (response) => {
                const results: Record<string, number> = {}
                response?.results.forEach((log: Record<string, any>) => {
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
