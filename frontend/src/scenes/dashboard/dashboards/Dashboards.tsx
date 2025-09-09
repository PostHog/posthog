import { useActions, useValues } from 'kea'

import { AccessControlledLemonButton } from 'lib/components/AccessControlledLemonButton'
import { PageHeader } from 'lib/components/PageHeader'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { getAppContext } from 'lib/utils/getAppContext'
import { DeleteDashboardModal } from 'scenes/dashboard/DeleteDashboardModal'
import { DuplicateDashboardModal } from 'scenes/dashboard/DuplicateDashboardModal'
import { NewDashboardModal } from 'scenes/dashboard/NewDashboardModal'
import { DashboardsTableContainer } from 'scenes/dashboard/dashboards/DashboardsTable'
import { DashboardsTab, dashboardsLogic } from 'scenes/dashboard/dashboards/dashboardsLogic'
import { DashboardTemplatesTable } from 'scenes/dashboard/dashboards/templates/DashboardTemplatesTable'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
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
    const newSceneLayout = useFeatureFlag('NEW_SCENE_LAYOUT')

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
            <PageHeader
                buttons={
                    <AccessControlledLemonButton
                        data-attr="new-dashboard"
                        onClick={() => {
                            showNewDashboardModal()
                        }}
                        type="primary"
                        minAccessLevel={AccessControlLevel.Editor}
                        resourceType={AccessControlResourceType.Dashboard}
                        userAccessLevel={
                            getAppContext()?.resource_access_control?.[AccessControlResourceType.Dashboard]
                        }
                    >
                        New dashboard
                    </AccessControlledLemonButton>
                }
            />
            <SceneTitleSection
                name="Dashboards"
                description="Create and manage your dashboards"
                resourceType={{
                    type: 'dashboard',
                }}
            />
            <SceneDivider />
            <LemonTabs
                activeKey={currentTab}
                onChange={(newKey) => setCurrentTab(newKey)}
                tabs={enabledTabs}
                sceneInset={newSceneLayout}
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
