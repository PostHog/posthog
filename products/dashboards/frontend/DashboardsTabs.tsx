import { useActions, useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { DashboardsTab, dashboardsLogic } from 'scenes/dashboard/dashboards/dashboardsLogic'

export function DashboardsTabs(): JSX.Element {
    const { setCurrentTab } = useActions(dashboardsLogic)
    const { currentTab } = useValues(dashboardsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const byProductFlag = featureFlags[FEATURE_FLAGS.DASHBOARDS_BY_PRODUCT]
    const byProductEnabled = byProductFlag === true || byProductFlag === 'test'
    const crossProjectEnabled = !!featureFlags[FEATURE_FLAGS.CROSS_PROJECT_DASHBOARDS]
    const enabledTabs: LemonTab<DashboardsTab>[] = [
        {
            key: DashboardsTab.All,
            label: 'All',
        },
        { key: DashboardsTab.Yours, label: 'Mine' },
        ...(crossProjectEnabled ? [{ key: DashboardsTab.CrossProject, label: 'Cross-project' }] : []),
        ...(byProductEnabled
            ? [{ key: DashboardsTab.ByProduct, label: 'By product', 'data-attr': 'dashboard-by-product-tab' }]
            : []),
    ]

    return (
        <LemonTabs
            onChange={setCurrentTab}
            activeKey={currentTab === DashboardsTab.ByProduct && !byProductEnabled ? DashboardsTab.All : currentTab}
            tabs={enabledTabs}
            sceneInset
        />
    )
}
