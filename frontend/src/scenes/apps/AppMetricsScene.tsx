import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { Tabs } from 'antd'
import { appMetricsSceneLogic, AppMetricsTab } from 'scenes/apps/appMetricsSceneLogic'
import { PageHeader } from 'lib/components/PageHeader'
import { useValues, useActions } from 'kea'
import { MetricsTab } from './MetricsTab'

export const scene: SceneExport = {
    component: AppMetrics,
    logic: appMetricsSceneLogic,
    paramsToProps: ({ params: { pluginConfigId } }) => ({ pluginConfigId: parseInt(pluginConfigId) ?? 0 }),
}

export function AppMetrics(): JSX.Element {
    const { activeTab } = useValues(appMetricsSceneLogic)
    const { setActiveTab } = useActions(appMetricsSceneLogic)

    return (
        <div>
            <PageHeader title="App metrics" caption="Here you can find metrics and details about your App" />

            <Tabs
                tabPosition="top"
                animated={false}
                activeKey={activeTab}
                onTabClick={(key) => setActiveTab(key as AppMetricsTab)}
            >
                <Tabs.TabPane tab="Metrics" key={AppMetricsTab.Metrics}>
                    <MetricsTab />
                </Tabs.TabPane>
                <Tabs.TabPane tab="Historical Exports" key={AppMetricsTab.HistoricalExports}>
                    <div>Hello!</div>
                </Tabs.TabPane>
            </Tabs>
        </div>
    )
}
