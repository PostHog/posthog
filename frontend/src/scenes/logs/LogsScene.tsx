import { LemonTable } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { Sparkline } from 'lib/lemon-ui/Sparkline'
import { logsSceneLogic } from 'scenes/logs/logsSceneLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { NodeKind } from '~/queries/schema'

import { logsDataLogic } from './logsDataLogic'

export const scene: SceneExport = {
    component: LogsScene,
    logic: logsSceneLogic,
}

export function LogsScene(): JSX.Element {
    const builtDataLogic = logsDataLogic({
        key: 'logs',
        query: {
            kind: NodeKind.LogsQuery,
            dateRange: {
                date_from: '7d',
            },
        },
    })

    const { response, responseLoading, sparklineData } = useValues(builtDataLogic)

    return (
        <div className="flex flex-col space-y-2 px-4 py-2">
            <div className="py-2">
                <Sparkline labels={sparklineData.labels} data={sparklineData.data} loading={responseLoading} />
            </div>
            <LemonTable
                dataSource={response?.results ?? []}
                loading={responseLoading}
                columns={[
                    {
                        title: 'Timestamp',
                        key: 'timestamp',
                        render: (_, log) => {
                            return log.timestamp
                        },
                    },
                    {
                        title: 'Level',
                        key: 'level',
                        render: (_, log) => {
                            return log.level
                        },
                    },
                    {
                        title: 'Message',
                        key: 'msg',
                        render: (_, log) => {
                            return log.msg
                        },
                    },
                ]}
            />
        </div>
    )
}
