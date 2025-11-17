import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { DeleteDashboardModal } from 'scenes/dashboard/DeleteDashboardModal'
import { DuplicateDashboardModal } from 'scenes/dashboard/DuplicateDashboardModal'
import { NewDashboardModal } from 'scenes/dashboard/NewDashboardModal'
import { DashboardsTableContainer } from 'scenes/dashboard/dashboards/DashboardsTable'
import { DashboardsTab, dashboardsLogic } from 'scenes/dashboard/dashboards/dashboardsLogic'
import { DashboardTemplatesTable } from 'scenes/dashboard/dashboards/templates/DashboardTemplatesTable'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { dashboardsModel } from '~/models/dashboardsModel'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { DashboardTemplateChooser } from '../DashboardTemplateChooser'

export const scene: SceneExport = {
    component: Dashboards,
    logic: dashboardsLogic,
    settingSectionId: 'environment-product-analytics',
}

export function Dashboards(): JSX.Element {
    const { dashboardsLoading } = useValues(dashboardsModel)
    const { setCurrentTab } = useActions(dashboardsLogic)
    const { dashboards, currentTab, isFiltering } = useValues(dashboardsLogic)
    const { showNewDashboardModal } = useActions(newDashboardLogic)

    const enabledTabs: LemonTab<DashboardsTab>[] = [
        {
            key: DashboardsTab.All,
            label: 'All dashboards',
        },
        { key: DashboardsTab.Yours, label: 'My dashboards' },
        { key: DashboardsTab.Pinned, label: 'Pinned' },
        {
            key: DashboardsTab.Templates,
            label: 'Templates',
        },
    ]

    return (
        <SceneContent>
            <NewDashboardModal />
            <DuplicateDashboardModal />
            <DeleteDashboardModal />

            <SceneTitleSection
                name={sceneConfigurations[Scene.Dashboards].name}
                description={sceneConfigurations[Scene.Dashboards].description}
                resourceType={{
                    type: sceneConfigurations[Scene.Dashboards].iconType || 'default_icon_type',
                }}
                actions={
                    <>
                        <AccessControlAction
                            resourceType={AccessControlResourceType.Dashboard}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            <LemonButton
                                size="small"
                                data-attr="new-dashboard"
                                onClick={showNewDashboardModal}
                                type="primary"
                            >
                                New dashboard
                            </LemonButton>
                        </AccessControlAction>
                    </>
                }
            />
            <LemonTabs
                activeKey={currentTab}
                onChange={(newKey) => setCurrentTab(newKey)}
                tabs={enabledTabs}
                sceneInset
            />

            <div>
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
        </SceneContent>
    )
}
