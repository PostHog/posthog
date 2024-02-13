import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { dashboardsLogic, DashboardsTab } from 'scenes/dashboard/dashboards/dashboardsLogic'
import { DashboardsTableContainer } from 'scenes/dashboard/dashboards/DashboardsTable'
import { DashboardTemplatesTable } from 'scenes/dashboard/dashboards/templates/DashboardTemplatesTable'
import { DeleteDashboardModal } from 'scenes/dashboard/DeleteDashboardModal'
import { DuplicateDashboardModal } from 'scenes/dashboard/DuplicateDashboardModal'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { NewDashboardModal } from 'scenes/dashboard/NewDashboardModal'
import { SceneExport } from 'scenes/sceneTypes'

import { dashboardsModel } from '~/models/dashboardsModel'

import { DashboardTemplateChooser } from '../DashboardTemplateChooser'

export const scene: SceneExport = {
    component: Dashboards,
    logic: dashboardsLogic,
}

export function Dashboards(): JSX.Element {
    const { dashboardsLoading } = useValues(dashboardsModel)
    const { setCurrentTab } = useActions(dashboardsLogic)
    const { dashboards, currentTab, isFiltering } = useValues(dashboardsLogic)
    const { showNewDashboardModal } = useActions(newDashboardLogic)

    const enabledTabs: LemonTab<DashboardsTab>[] = [
        {
            key: DashboardsTab.Dashboards,
            label: 'Dashboards',
        },
        {
            key: DashboardsTab.Templates,
            label: 'Templates',
        },
    ]

    return (
        <div>
            <NewDashboardModal />
            <DuplicateDashboardModal />
            <DeleteDashboardModal />
            <PageHeader
                buttons={
                    <LemonButton
                        data-attr="new-dashboard"
                        onClick={() => {
                            showNewDashboardModal()
                        }}
                        type="primary"
                    >
                        New dashboard
                    </LemonButton>
                }
            />
            <LemonTabs activeKey={currentTab} onChange={(newKey) => setCurrentTab(newKey)} tabs={enabledTabs} />
            {currentTab === DashboardsTab.Templates ? (
                <DashboardTemplatesTable />
            ) : dashboardsLoading || dashboards.length > 0 || isFiltering ? (
                <DashboardsTableContainer />
            ) : (
                <div className="mt-4">
                    <p>Create your first dashboard:</p>
                    <DashboardTemplateChooser />
                </div>
            )}
        </div>
    )
}
