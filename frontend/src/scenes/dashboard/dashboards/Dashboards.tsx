import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { GraphsHog } from 'lib/components/hedgehogs'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { DashboardsTab, dashboardsLogic } from 'scenes/dashboard/dashboards/dashboardsLogic'
import { DashboardsTableContainer } from 'scenes/dashboard/dashboards/DashboardsTable'
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

import { FeaturedTemplatesChooser } from './templates/FeaturedTemplatesChooser'

const DASHBOARD_DOCS_URL = 'https://posthog.com/docs/product-analytics/dashboards'

export const scene: SceneExport = {
    component: Dashboards,
    logic: dashboardsLogic,
    productKey: ProductKey.PRODUCT_ANALYTICS,
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
                            <AppShortcut
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
                            </AppShortcut>
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
                    <ProductIntroduction
                        productName="Dashboards"
                        thingName="dashboard"
                        titleOverride="Your home for what you actually care about"
                        description="Keep analytics, session replay, logs, and the rest of your PostHog stack in one place. Below are customer-favorite dashboards to get you started quickly. Or skip them and start blank, up to you."
                        isEmpty={true}
                        docsURL={DASHBOARD_DOCS_URL}
                        customHog={GraphsHog}
                        hogLayout="responsive"
                        useMainContentContainerQueries={true}
                        contentClassName="max-w-[1000px]"
                        actionElementOverride={<FeaturedTemplatesChooser />}
                    />
                )}
            </div>
        </SceneContent>
    )
}
