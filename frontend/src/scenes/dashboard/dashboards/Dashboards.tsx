import { useActions, useValues } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
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
import { DashboardTemplatesTable } from 'scenes/dashboard/dashboards/templates/DashboardTemplatesTable'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'

export const scene: SceneExport = {
    component: Dashboards,
    logic: dashboardsLogic,
}

export function Dashboards(): JSX.Element {
    const { dashboardsLoading } = useValues(dashboardsModel)
    const { setSearchTerm, setCurrentTab } = useActions(dashboardsLogic)
    const { dashboards, searchTerm, currentTab, templatesTabIsVisible } = useValues(dashboardsLogic)
    const { showNewDashboardModal } = useActions(newDashboardLogic)
    const { closePrompts } = useActions(inAppPromptLogic)

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
            <LemonTabs
                activeKey={currentTab}
                onChange={(newKey) => setCurrentTab(newKey)}
                tabs={[
                    {
                        key: DashboardsTab.All,
                        label: 'All dashboards',
                    },
                    {
                        key: DashboardsTab.Yours,
                        label: 'Your dashboards',
                    },
                    {
                        key: DashboardsTab.Pinned,
                        label: 'Pinned',
                    },
                    {
                        key: DashboardsTab.Shared,
                        label: 'Shared',
                    },
                    templatesTabIsVisible && {
                        key: DashboardsTab.Templates,
                        label: 'Templates',
                    },
                ]}
            />
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
