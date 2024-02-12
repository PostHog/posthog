import { useValues } from 'kea'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { PipelineNodeLogs } from 'scenes/pipeline/PipelineNodeLogs'

import { PipelineStage } from '~/types'

import { appMetricsSceneLogic } from './appMetricsSceneLogic'

export function AppLogsTab(): JSX.Element {
    const { activeTab, pluginConfig, pluginConfigLoading } = useValues(appMetricsSceneLogic)

    if (!pluginConfig || pluginConfigLoading || !activeTab) {
        return <LemonSkeleton />
    }

    return (
        <div className="space-y-8">
            <PipelineNodeLogs id={pluginConfig.id} stage={PipelineStage.Destination} />
        </div>
    )
}
