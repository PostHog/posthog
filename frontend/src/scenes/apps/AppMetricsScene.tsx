import { SceneExport } from 'scenes/sceneTypes'
import { appMetricsSceneLogic, AppMetricsTab } from 'scenes/apps/appMetricsSceneLogic'
import { PageHeader } from 'lib/components/PageHeader'
import { useValues, useActions } from 'kea'
import { MetricsTab } from './MetricsTab'
import { HistoricalExportsTab } from './HistoricalExportsTab'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { ErrorDetailsModal } from './ErrorDetailsModal'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { ActivityScope } from 'lib/components/ActivityLog/humanizeActivity'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { PluginTags } from 'scenes/plugins/tabs/apps/components'
import { PluginImage } from 'scenes/plugins/plugin/PluginImage'
import { AppLogsTab } from './AppLogsTab'
import { LemonButton } from '@posthog/lemon-ui'
import { IconSettings } from 'lib/lemon-ui/icons'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'

export const scene: SceneExport = {
    component: AppMetrics,
    logic: appMetricsSceneLogic,
    paramsToProps: ({ params: { pluginConfigId } }) => ({ pluginConfigId: parseInt(pluginConfigId) ?? 0 }),
}

export function AppMetrics(): JSX.Element {
    const { activeTab, pluginConfig, pluginConfigLoading, showTab } = useValues(appMetricsSceneLogic)
    const { editPlugin } = useActions(pluginsLogic)
    const { setActiveTab } = useActions(appMetricsSceneLogic)

    return (
        <div>
            <div className="flex items-center gap-2">
                {pluginConfig ? (
                    <PluginImage plugin={pluginConfig?.plugin_info} />
                ) : (
                    <LemonSkeleton className="w-10 h-10" />
                )}
                <div className="flex-1">
                    <PageHeader
                        title={
                            pluginConfig ? (
                                <span className="flex items-center gap-2">
                                    {pluginConfig.plugin_info.name}
                                    <PluginTags plugin={pluginConfig.plugin_info} />
                                </span>
                            ) : (
                                <LemonSkeleton />
                            )
                        }
                        caption={pluginConfig ? 'An overview of metrics and exports for this app.' : undefined}
                        buttons={
                            pluginConfig?.plugin ? (
                                <LemonButton
                                    type="primary"
                                    icon={<IconSettings />}
                                    onClick={() => editPlugin(pluginConfig?.plugin)}
                                >
                                    Configure
                                </LemonButton>
                            ) : undefined
                        }
                    />
                </div>
            </div>

            {pluginConfigLoading || !activeTab ? (
                <LemonSkeleton />
            ) : (
                <LemonTabs
                    activeKey={activeTab}
                    onChange={(newKey) => setActiveTab(newKey)}
                    tabs={[
                        showTab(AppMetricsTab.ProcessEvent) && {
                            key: AppMetricsTab.ProcessEvent,
                            label: <>processEvent metrics</>,
                            content: <MetricsTab tab={AppMetricsTab.ProcessEvent} />,
                        },
                        showTab(AppMetricsTab.OnEvent) && {
                            key: AppMetricsTab.OnEvent,
                            label: <>onEvent metrics</>,
                            content: <MetricsTab tab={AppMetricsTab.OnEvent} />,
                        },
                        showTab(AppMetricsTab.ComposeWebhook) && {
                            key: AppMetricsTab.ComposeWebhook,
                            label: <>composeWebhook metrics</>,
                            content: <MetricsTab tab={AppMetricsTab.ComposeWebhook} />,
                        },
                        showTab(AppMetricsTab.ExportEvents) && {
                            key: AppMetricsTab.ExportEvents,
                            label: <>exportEvents metrics</>,
                            content: <MetricsTab tab={AppMetricsTab.ExportEvents} />,
                        },
                        showTab(AppMetricsTab.ScheduledTask) && {
                            key: AppMetricsTab.ScheduledTask,
                            label: 'Scheduled tasks',
                            tooltip: 'Metrics for app methods `runEveryMinute`, `runEveryHour` and `runEveryDay`.',
                            content: <MetricsTab tab={AppMetricsTab.ScheduledTask} />,
                        },
                        showTab(AppMetricsTab.HistoricalExports) && {
                            key: AppMetricsTab.HistoricalExports,
                            label: 'Historical exports',
                            content: <HistoricalExportsTab />,
                        },
                        {
                            key: AppMetricsTab.Logs,
                            label: 'Logs',
                            content: <AppLogsTab />,
                        },
                        {
                            key: AppMetricsTab.History,
                            label: 'History',
                            content: <ActivityLog scope={ActivityScope.PLUGIN} id={pluginConfig?.id} />,
                        },
                    ]}
                />
            )}

            <ErrorDetailsModal />
        </div>
    )
}
