import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { Tabs } from 'antd'
import { appMetricsSceneLogic, AppMetricsTab } from 'scenes/apps/appMetricsSceneLogic'
import { PageHeader } from 'lib/components/PageHeader'
import { useValues, useActions } from 'kea'
import { MetricsTab } from './MetricsTab'
import { HistoricalExportsTab } from './HistoricalExportsTab'
import { LemonSkeleton } from '../../lib/components/LemonSkeleton'

export const scene: SceneExport = {
    component: AppMetrics,
    logic: appMetricsSceneLogic,
    paramsToProps: ({ params: { pluginConfigId } }) => ({ pluginConfigId: parseInt(pluginConfigId) ?? 0 }),
}

export function AppMetrics(): JSX.Element {
    const { activeTab, pluginConfigLoading } = useValues(appMetricsSceneLogic)
    const { setActiveTab } = useActions(appMetricsSceneLogic)

    if (pluginConfigLoading) {
        return <LemonSkeleton />
    }

    return (
        <div>
            <PageHeader title="App metrics" caption="Here you can find metrics and details about your App" />

            {pluginConfigLoading ? (
                <LemonSkeleton />
            ) : (
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
                        <HistoricalExportsTab />
                    </Tabs.TabPane>
                </Tabs>
            )}
        </div>
    )
}
