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
import { LemonInput, LemonSelect } from '@posthog/lemon-ui'
import { DeleteDashboardModal } from 'scenes/dashboard/DeleteDashboardModal'
import { DuplicateDashboardModal } from 'scenes/dashboard/DuplicateDashboardModal'
import { NoDashboards } from 'scenes/dashboard/dashboards/NoDashboards'
import { DashboardsTable } from 'scenes/dashboard/dashboards/DashboardsTable'
import { DashboardTemplatesTable } from 'scenes/dashboard/dashboards/templates/DashboardTemplatesTable'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { IconPinOutline, IconShare } from 'lib/lemon-ui/icons'
import { membersLogic } from 'scenes/organization/Settings/membersLogic'

export const scene: SceneExport = {
    component: Dashboards,
    logic: dashboardsLogic,
}

export function Dashboards(): JSX.Element {
    const { dashboardsLoading } = useValues(dashboardsModel)
    const { setCurrentTab, setFilters } = useActions(dashboardsLogic)
    const { dashboards, currentTab, filters } = useValues(dashboardsLogic)
    const { showNewDashboardModal } = useActions(newDashboardLogic)
    const { closePrompts } = useActions(inAppPromptLogic)
    const { meFirstMembers } = useValues(membersLogic)

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
                        key: DashboardsTab.Dashboards,
                        label: 'Dashboards',
                    },
                    {
                        key: DashboardsTab.Templates,
                        label: 'Templates',
                    },
                ]}
            />
            <div className="flex justify-between gap-2 flex-wrap">
                <LemonInput
                    type="search"
                    placeholder="Search for dashboards"
                    onChange={(x) => setFilters({ search: x })}
                    value={filters.search}
                />
                <div className="flex items-center gap-4 flex-wrap">
                    <div className="flex items-center gap-2">
                        <LemonButton
                            active={filters.pinned}
                            type="secondary"
                            status="stealth"
                            size="small"
                            onClick={() => setFilters({ pinned: !filters.pinned })}
                            icon={<IconPinOutline />}
                        >
                            Pinned
                        </LemonButton>
                    </div>
                    <div className="flex items-center gap-2">
                        <LemonButton
                            active={filters.shared}
                            type="secondary"
                            status="stealth"
                            size="small"
                            onClick={() => setFilters({ shared: !filters.shared })}
                            icon={<IconShare />}
                        >
                            Shared
                        </LemonButton>
                    </div>
                    <div className="flex items-center gap-2">
                        <span>Created by:</span>
                        <LemonSelect
                            options={[
                                { value: 'All users' as number | 'All users', label: 'All Users' },
                                ...meFirstMembers.map((x) => ({
                                    value: x.user.id,
                                    label: x.user.first_name,
                                })),
                            ]}
                            size="small"
                            value={filters.createdBy}
                            onChange={(v: any): void => {
                                setFilters({ createdBy: v })
                            }}
                            dropdownMatchSelectWidth={false}
                        />
                    </div>
                </div>
            </div>
            <LemonDivider className="my-4" />
            {currentTab === DashboardsTab.Templates ? (
                <DashboardTemplatesTable />
            ) : dashboardsLoading || dashboards.length > 0 || filters.search ? (
                <DashboardsTable />
            ) : (
                <NoDashboards />
            )}
        </div>
    )
}
