import { appMetricsSceneLogic } from './appMetricsSceneLogic'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { useValues } from 'kea'
import { PluginLogs } from 'scenes/plugins/plugin/PluginLogs'

export function AppLogsTab(): JSX.Element {
    const { activeTab, pluginConfig, pluginConfigLoading } = useValues(appMetricsSceneLogic)

    if (!pluginConfig || pluginConfigLoading || !activeTab) {
        return <LemonSkeleton />
    }

    return (
        <div className="space-y-8">
            <PluginLogs pluginConfigId={pluginConfig.id} />
        </div>
    )
}
