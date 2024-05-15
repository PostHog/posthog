import { connect, kea, path, props } from 'kea'

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
])
