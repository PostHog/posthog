import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
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
    const { loadDashboards } = useActions(dashboardsModel)
    const { setCurrentTab } = useActions(dashboardsLogic)
    const { currentTab, listState } = useValues(dashboardsLogic)
    const { showNewDashboardModal } = useActions(newDashboardLogic)

    useEffect(() => {
        if ((listState === 'empty' || listState === 'load-failed') && currentTab !== DashboardsTab.Templates) {
            // pinned: analytics event name - renaming breaks dashboards
            posthog.capture('dashboards list showed nothing', { state: listState, tab: currentTab })
        }
    }, [listState, currentTab])
    const enabledTabs: LemonTab<DashboardsTab>[] = [
        {
            key: DashboardsTab.All,
            label: 'All dashboards',
        },
        { key: DashboardsTab.Yours, label: 'My dashboards' },
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

            <div>
                {currentTab === DashboardsTab.Templates ? (
                    <DashboardTemplatesTable />
                ) : listState === 'load-failed' ? (
                    <LemonBanner
                        type="error"
                        action={{
                            children: 'Try again',
                            onClick: () => loadDashboards(),
                            'data-attr': 'dashboards-retry-load',
                        }}
                    >
                        Couldn't load your dashboards. Try again, and if it keeps happening contact support.
                    </LemonBanner>
                ) : (
                    <DashboardsTableContainer />
                )}
            </div>
        </SceneContent>
    )
}
