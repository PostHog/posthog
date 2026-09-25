import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { DashboardsTab, dashboardsLogic } from 'scenes/dashboard/dashboards/dashboardsLogic'
import { DashboardTemplateModal } from 'scenes/dashboard/dashboards/templates/DashboardTemplateModal'
import { DashboardTemplatesTable } from 'scenes/dashboard/dashboards/templates/DashboardTemplatesTable'
import { DashboardTemplateEditor } from 'scenes/dashboard/DashboardTemplateEditor'
import { DeleteDashboardModal } from 'scenes/dashboard/DeleteDashboardModal'
import { DuplicateDashboardModal } from 'scenes/dashboard/DuplicateDashboardModal'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { NewDashboardModal } from 'scenes/dashboard/NewDashboardModal'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { dashboardsModel } from '~/models/dashboardsModel'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { dashboardsEmptyState } from 'products/dashboards/frontend/emptyState/dashboardsEmptyState'
import { DashboardSavedViews } from 'products/dashboards/frontend/saved-views/DashboardSavedViews'

import { DashboardsTableContainer } from './DashboardsTable'

export const scene: SceneExport = {
    component: Dashboards,
    logic: dashboardsLogic,
    productKey: ProductKey.PRODUCT_ANALYTICS,
    emptyState: dashboardsEmptyState,
}

export function Dashboards(): JSX.Element {
    const { searchParams } = useValues(router)
    const { dashboardsLoading } = useValues(dashboardsModel)
    const { setCurrentTab } = useActions(dashboardsLogic)
    const { dashboards, currentTab, isFiltering } = useValues(dashboardsLogic)
    const { showNewDashboardModal } = useActions(newDashboardLogic)
    const templatesModalOpen = String(searchParams.templates) === '1'
    const enabledTabs: LemonTab<DashboardsTab>[] = [
        {
            key: DashboardsTab.All,
            label: 'All dashboards',
        },
        { key: DashboardsTab.Yours, label: 'My dashboards' },
    ]

    return (
        <SceneContent>
            <NewDashboardModal />
            <DuplicateDashboardModal />
            <DeleteDashboardModal />
            <LemonModal
                title="Dashboard templates"
                isOpen={templatesModalOpen}
                onClose={() =>
                    router.actions.push(urls.dashboards(), {
                        ...searchParams,
                        templates: undefined,
                        templateFilter: undefined,
                    })
                }
                width="min(1200px, calc(100vw - 3rem))"
                data-attr="dashboard-templates-modal"
            >
                {templatesModalOpen && <DashboardTemplatesTable />}
            </LemonModal>
            <DashboardTemplateEditor />
            <DashboardTemplateModal />

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
                            <Shortcut
                                name="NewDashboard"
                                keybind={[keyBinds.new]}
                                intent="New dashboard"
                                interaction="click"
                                scope={Scene.Dashboards}
                            >
                                <LemonButton
                                    size="small"
                                    data-attr="new-dashboard"
                                    onClick={showNewDashboardModal}
                                    type="primary"
                                    sideAction={{
                                        icon: <IconChevronDown />,
                                        tooltip: 'View dashboard templates',
                                        'aria-label': 'View dashboard templates',
                                        'data-attr': 'view-dashboard-templates',
                                        onClick: () =>
                                            router.actions.push(urls.dashboards(), { ...searchParams, templates: '1' }),
                                    }}
                                >
                                    New dashboard
                                </LemonButton>
                            </Shortcut>
                        </AccessControlAction>
                    </>
                }
            />
            <LemonTabs
                onChange={(newKey) => {
                    setCurrentTab(newKey)
                }}
                activeKey={currentTab}
                tabs={enabledTabs}
                sceneInset
                rightSlot={<DashboardSavedViews />}
                rightSlotClassName="!static !justify-start !bg-transparent"
            />

            <div>{dashboardsLoading || dashboards.length > 0 || isFiltering ? <DashboardsTableContainer /> : null}</div>
        </SceneContent>
    )
}
