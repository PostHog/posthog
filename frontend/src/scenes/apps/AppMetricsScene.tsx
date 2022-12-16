import { SceneExport } from 'scenes/sceneTypes'
import { Tabs } from 'antd'
import { appMetricsSceneLogic, AppMetricsTab } from 'scenes/apps/appMetricsSceneLogic'
import { PageHeader } from 'lib/components/PageHeader'
import { useValues, useActions } from 'kea'
import { MetricsTab } from './MetricsTab'
import { HistoricalExportsTab } from './HistoricalExportsTab'
import { LemonSkeleton } from 'lib/components/LemonSkeleton'
import { ErrorDetailsModal } from './ErrorDetailsModal'
import { Tooltip } from 'lib/components/Tooltip'
import { IconInfo } from 'lib/components/icons'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { ActivityScope } from 'lib/components/ActivityLog/humanizeActivity'
import { TabItem } from '~/types'

export const scene: SceneExport = {
    component: AppMetrics,
    logic: appMetricsSceneLogic,
    paramsToProps: ({ params: { pluginConfigId } }) => ({ pluginConfigId: parseInt(pluginConfigId) ?? 0 }),
}

export function AppMetrics(): JSX.Element {
    const { activeTab, pluginConfig, pluginConfigLoading, showTab, shouldShowAppMetrics } =
        useValues(appMetricsSceneLogic)
    const { setActiveTab } = useActions(appMetricsSceneLogic)

    const getTabItems = (): TabItem[] => {
        const tabItems: TabItem[] = []
        showTab(AppMetricsTab.ProcessEvent) &&
            tabItems.push({
                label: 'processEvent metrics',
                key: AppMetricsTab.ProcessEvent,
                children: <MetricsTab tab={AppMetricsTab.ProcessEvent} />,
            })
        showTab(AppMetricsTab.OnEvent) &&
            tabItems.push({
                label: 'onEvent metrics',
                key: AppMetricsTab.OnEvent,
                children: <MetricsTab tab={AppMetricsTab.OnEvent} />,
            })

        showTab(AppMetricsTab.ExportEvents) && {
            label: 'exportEvents metrics',
            key: AppMetricsTab.ExportEvents,
            children: <MetricsTab tab={AppMetricsTab.ExportEvents} />,
        }
        showTab(AppMetricsTab.ScheduledTask) &&
            tabItems.push({
                label: (
                    <>
                        Scheduled tasks{' '}
                        <Tooltip
                            title={'Shows metrics for app methods `runEveryMinute`, `runEveryHour` and `runEveryDay`'}
                        >
                            <IconInfo />
                        </Tooltip>
                    </>
                ),

                key: AppMetricsTab.ScheduledTask,
                children: <MetricsTab tab={AppMetricsTab.ScheduledTask} />,
            })
        showTab(AppMetricsTab.HistoricalExports) &&
            tabItems.push({
                label: 'Historical exports',
                key: AppMetricsTab.HistoricalExports,
                children: <HistoricalExportsTab />,
            })
        tabItems.push({
            label: 'History',
            key: AppMetricsTab.History,
            children: <ActivityLog scope={ActivityScope.PLUGIN} id={pluginConfig?.id} />,
        })
        return tabItems
    }

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
                    items={getTabItems()}
                />
            )}

            <ErrorDetailsModal />
        </div>
    )
}
