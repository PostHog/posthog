import { useActions, useValues } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { dashboardsLogic, DashboardsTab } from 'scenes/dashboard/dashboards/dashboardsLogic'
import { NewDashboardModal } from 'scenes/dashboard/NewDashboardModal'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { inAppPromptLogic } from 'lib/logic/inAppPrompt/inAppPromptLogic'
import { DeleteDashboardModal } from 'scenes/dashboard/DeleteDashboardModal'
import { DuplicateDashboardModal } from 'scenes/dashboard/DuplicateDashboardModal'
import { NoDashboards } from 'scenes/dashboard/dashboards/NoDashboards'
import { DashboardsTableContainer } from 'scenes/dashboard/dashboards/DashboardsTable'
import { DashboardTemplatesTable } from 'scenes/dashboard/dashboards/templates/DashboardTemplatesTable'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { NotebooksTable } from 'scenes/notebooks/NotebooksTable/NotebooksTable'
import { notebooksListLogic } from 'scenes/notebooks/Notebook/notebooksListLogic'
import { LemonTag } from '@posthog/lemon-ui'

export const scene: SceneExport = {
    component: Dashboards,
    logic: dashboardsLogic,
}

export function Dashboards(): JSX.Element {
    const { dashboardsLoading } = useValues(dashboardsModel)
    const { setCurrentTab } = useActions(dashboardsLogic)
    const { dashboards, currentTab, isFiltering } = useValues(dashboardsLogic)
    const { showNewDashboardModal } = useActions(newDashboardLogic)
    const { closePrompts } = useActions(inAppPromptLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { notebooksLoading } = useValues(notebooksListLogic)
    const { createNotebook } = useActions(notebooksListLogic)

    const notebooksEnabled = featureFlags[FEATURE_FLAGS.NOTEBOOKS]

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
    if (notebooksEnabled) {
        enabledTabs.splice(1, 0, {
            key: DashboardsTab.Notebooks,
            label: (
                <>
                    Notebooks
                    <LemonTag type="warning" className="uppercase ml-2">
                        Beta
                    </LemonTag>
                </>
            ),
        })
    }

    return (
        <div>
            <NewDashboardModal />
            <DuplicateDashboardModal />
            <DeleteDashboardModal />
            <PageHeader
                title={'Dashboards' + (notebooksEnabled ? ' & Notebooks' : '')}
                buttons={
                    currentTab === DashboardsTab.Notebooks ? (
                        <LemonButton
                            data-attr={'new-notebook'}
                            onClick={() => {
                                createNotebook()
                            }}
                            type="primary"
                            disabledReason={notebooksLoading ? 'Loading...' : undefined}
                        >
                            New notebook
                        </LemonButton>
                    ) : (
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
                    )
                }
            />
            <LemonTabs activeKey={currentTab} onChange={(newKey) => setCurrentTab(newKey)} tabs={enabledTabs} />
            {currentTab === DashboardsTab.Templates ? (
                <DashboardTemplatesTable />
            ) : currentTab === DashboardsTab.Notebooks ? (
                <NotebooksTable />
            ) : dashboardsLoading || dashboards.length > 0 || isFiltering ? (
                <DashboardsTableContainer />
            ) : (
                <NoDashboards />
            )}
        </div>
    )
}
