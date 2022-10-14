import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { Tabs } from 'antd'
import { appMetricsSceneLogic, AppMetricsTab } from 'scenes/apps/appMetricsSceneLogic'
import { PageHeader } from 'lib/components/PageHeader'
import { useValues, useActions } from 'kea'
import { MetricsTab } from './MetricsTab'
import { HistoricalExportsTab } from './HistoricalExportsTab'
import { LemonSkeleton } from '../../lib/components/LemonSkeleton'
import { ErrorDetailsDrawer } from './ErrorDetailsDrawer'

export const scene: SceneExport = {
    component: AppMetrics,
    logic: appMetricsSceneLogic,
    paramsToProps: ({ params: { pluginConfigId } }) => ({ pluginConfigId: parseInt(pluginConfigId) ?? 0 }),
}

export function AppMetrics(): JSX.Element {
    const { activeTab, pluginConfig, pluginConfigLoading, showTab } = useValues(appMetricsSceneLogic)
    const { setActiveTab } = useActions(appMetricsSceneLogic)

    return (
        <div>
            <PageHeader
                title={pluginConfig ? pluginConfig.plugin_info.name : <LemonSkeleton />}
                caption="An overview of metrics and export for this app."
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
                    {showTab(AppMetricsTab.HistoricalExports) && (
                        <Tabs.TabPane tab="Historical Exports" key={AppMetricsTab.HistoricalExports}>
                            <HistoricalExportsTab />
                        </Tabs.TabPane>
                    )}
                </Tabs>
            )}

            <ErrorDetailsDrawer />
        </div>
    )
}
