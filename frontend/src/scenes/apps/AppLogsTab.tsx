import { useValues } from 'kea'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { PipelineAppLogs } from 'scenes/pipeline/PipelineAppLogs'

import { PipelineTabs } from '~/types'

import { appMetricsSceneLogic } from './appMetricsSceneLogic'

export function AppLogsTab(): JSX.Element {
    const { activeTab, pluginConfig, pluginConfigLoading } = useValues(appMetricsSceneLogic)

    if (!pluginConfig || pluginConfigLoading || !activeTab) {
        return <LemonSkeleton />
    }

    return (
        <div className="space-y-8">
            <PipelineAppLogs id={pluginConfig.id} kind={PipelineTabs.Destinations} />
        </div>
    )
}
