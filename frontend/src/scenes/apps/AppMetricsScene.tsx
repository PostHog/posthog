import { SceneExport } from 'scenes/sceneTypes'
import { Tabs } from 'antd'
import { appMetricsSceneLogic, AppMetricsTab } from 'scenes/apps/appMetricsSceneLogic'
import { PageHeader } from 'lib/components/PageHeader'
import { useValues, useActions } from 'kea'
import { MetricsTab } from './MetricsTab'
import { HistoricalExportsTab } from './HistoricalExportsTab'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { ErrorDetailsModal } from './ErrorDetailsModal'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconInfo } from 'lib/lemon-ui/icons'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { ActivityScope } from 'lib/components/ActivityLog/humanizeActivity'

export const scene: SceneExport = {
    component: AppMetrics,
    logic: appMetricsSceneLogic,
    paramsToProps: ({ params: { pluginConfigId } }) => ({ pluginConfigId: parseInt(pluginConfigId) ?? 0 }),
}

export function AppMetrics(): JSX.Element {
    const { activeTab, pluginConfig, pluginConfigLoading, showTab, shouldShowAppMetrics } =
        useValues(appMetricsSceneLogic)
    const { setActiveTab } = useActions(appMetricsSceneLogic)

    return (
        <div>
            <PageHeader
                title={pluginConfig ? pluginConfig.plugin_info.name : <LemonSkeleton />}
                caption={
                    shouldShowAppMetrics && pluginConfig
                        ? 'An overview of metrics and exports for this app.'
                        : undefined
                }
            />

            {pluginConfigLoading || !activeTab ? (
                <LemonSkeleton />
            ) : (
                <Tabs
                    tabPosition="top"
                    animated={false}
                    activeKey={activeTab}
                    onTabClick={(key) => setActiveTab(key as AppMetricsTab)}
                >
                    {showTab(AppMetricsTab.ProcessEvent) && (
                        <Tabs.TabPane tab="processEvent metrics" key={AppMetricsTab.ProcessEvent}>
                            <MetricsTab tab={AppMetricsTab.ProcessEvent} />
                        </Tabs.TabPane>
                    )}
                    {showTab(AppMetricsTab.OnEvent) && (
                        <Tabs.TabPane tab="onEvent metrics" key={AppMetricsTab.OnEvent}>
                            <MetricsTab tab={AppMetricsTab.OnEvent} />
                        </Tabs.TabPane>
                    )}
                    {showTab(AppMetricsTab.ExportEvents) && (
                        <Tabs.TabPane tab="exportEvents metrics" key={AppMetricsTab.ExportEvents}>
                            <MetricsTab tab={AppMetricsTab.ExportEvents} />
                        </Tabs.TabPane>
                    )}
                    {showTab(AppMetricsTab.ScheduledTask) && (
                        <Tabs.TabPane
                            tab={
                                <>
                                    Scheduled tasks{' '}
                                    <Tooltip
                                        title={
                                            'Shows metrics for app methods `runEveryMinute`, `runEveryHour` and `runEveryDay`'
                                        }
                                    >
                                        <IconInfo />
                                    </Tooltip>
                                </>
                            }
                            key={AppMetricsTab.ScheduledTask}
                        >
                            <MetricsTab tab={AppMetricsTab.ScheduledTask} />
                        </Tabs.TabPane>
                    )}
                    {showTab(AppMetricsTab.HistoricalExports) && (
                        <Tabs.TabPane tab="Historical exports" key={AppMetricsTab.HistoricalExports}>
                            <HistoricalExportsTab />
                        </Tabs.TabPane>
                    )}
                    <Tabs.TabPane tab="History" key={AppMetricsTab.History}>
                        <ActivityLog scope={ActivityScope.PLUGIN} id={pluginConfig?.id} />
                    </Tabs.TabPane>
                </Tabs>
            )}

            <ErrorDetailsModal />
        </div>
    )
}
