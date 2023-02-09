import { useActions, useValues } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { Tabs } from 'antd'
import { dashboardsLogic, DashboardsTab } from 'scenes/dashboard/dashboards/dashboardsLogic'
import { NewDashboardModal } from 'scenes/dashboard/NewDashboardModal'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { inAppPromptLogic } from 'lib/logic/inAppPrompt/inAppPromptLogic'
import { LemonInput } from '@posthog/lemon-ui'
import { DeleteDashboardModal } from 'scenes/dashboard/DeleteDashboardModal'
import { DuplicateDashboardModal } from 'scenes/dashboard/DuplicateDashboardModal'
import { NoDashboards } from 'scenes/dashboard/dashboards/NoDashboards'
import { DashboardsTable } from 'scenes/dashboard/dashboards/DashboardsTable'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { DashboardTemplatesTable } from 'scenes/dashboard/dashboards/templates/DashboardTemplatesTable'

export const scene: SceneExport = {
    component: Dashboards,
    logic: dashboardsLogic,
}

export function Dashboards(): JSX.Element {
    const { dashboardsLoading } = useValues(dashboardsModel)
    const { setSearchTerm, setCurrentTab } = useActions(dashboardsLogic)
    const { dashboards, searchTerm, currentTab } = useValues(dashboardsLogic)
    const { showNewDashboardModal } = useActions(newDashboardLogic)
    const { closePrompts } = useActions(inAppPromptLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <div>
            <NewDashboardModal />
            <DuplicateDashboardModal />
            <DeleteDashboardModal />
            <PageHeader
                title="Dashboards"
                buttons={
                    <LemonButton
                        data-attr={'new-dashboard'}
                        onClick={() => {
                            closePrompts()
                            showNewDashboardModal()
                        }}
                        type="primary"
                    >
                        New dashboard
                    </LemonButton>
                }
            />
            <Tabs
                activeKey={currentTab}
                style={{ borderColor: '#D9D9D9' }}
                onChange={(tab) => setCurrentTab(tab as DashboardsTab)}
            >
                <Tabs.TabPane tab="All Dashboards" key={DashboardsTab.All} />
                <Tabs.TabPane tab="Your Dashboards" key={DashboardsTab.Yours} />
                <Tabs.TabPane tab="Pinned" key={DashboardsTab.Pinned} />
                <Tabs.TabPane tab="Shared" key={DashboardsTab.Shared} />
                {!!featureFlags[FEATURE_FLAGS.DASHBOARD_TEMPLATES] && (
                    <Tabs.TabPane tab="Templates" key={DashboardsTab.Templates} />
                )}
            </Tabs>
            <div className="flex">
                <LemonInput
                    type="search"
                    placeholder="Search for dashboards"
                    onChange={setSearchTerm}
                    value={searchTerm}
                />
                <div />
            </div>
            <LemonDivider className="my-4" />
            {currentTab === DashboardsTab.Templates ? (
                <DashboardTemplatesTable />
            ) : dashboardsLoading || dashboards.length > 0 || searchTerm || currentTab !== DashboardsTab.All ? (
                <DashboardsTable />
            ) : (
                <NoDashboards />
            )}
        </div>
    )
}
