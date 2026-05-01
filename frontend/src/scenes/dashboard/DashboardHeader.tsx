import { useActions, useValues } from 'kea'

import { FullScreen } from 'lib/components/FullScreen'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { dashboardsModel } from '~/models/dashboardsModel'
import { DashboardMode } from '~/types'

import { EditModeActions, FullscreenModeActions, ViewModeActions } from './DashboardHeaderActions'
import { DashboardLoadAction, dashboardLogic } from './dashboardLogic'
import { DashboardModals } from './DashboardModals'
import { DashboardScenePanel } from './DashboardScenePanel'

export const DASHBOARD_CANNOT_EDIT_MESSAGE =
    "You don't have edit permissions for this dashboard. Ask a dashboard collaborator with edit access to add you."

export function DashboardHeader(): JSX.Element | null {
    const { dashboard, dashboardLoading, dashboardMode, canEditDashboard } = useValues(dashboardLogic)
    const { setDashboardMode, loadDashboard } = useActions(dashboardLogic)
    const { updateDashboard } = useActions(dashboardsModel)

    if (!dashboard && !dashboardLoading) {
        return null
    }

    return (
        <>
            {dashboardMode === DashboardMode.Fullscreen && (
                <FullScreen onExit={() => setDashboardMode(null, DashboardEventSource.Browser)} />
            )}

            {dashboard && <DashboardModals dashboard={dashboard} />}

            <DashboardScenePanel />

            <SceneTitleSection
                name={dashboard?.name}
                description={dashboard?.description}
                resourceType={{
                    type: sceneConfigurations[Scene.Dashboard].iconType || 'default_icon_type',
                }}
                onNameChange={(value) => {
                    updateDashboard({ id: dashboard?.id, name: value, allowUndo: true })
                }}
                onDescriptionChange={(value) => {
                    updateDashboard({ id: dashboard?.id, description: value, allowUndo: true })
                }}
                markdown
                canEdit={canEditDashboard}
                isLoading={dashboardLoading}
                saveOnBlur
                renameDebounceMs={0}
                maxToolProps={
                    dashboard && canEditDashboard
                        ? {
                              identifier: 'upsert_dashboard',
                              context: {
                                  current_dashboard: {
                                      id: dashboard.id,
                                      name: dashboard.name,
                                      description: dashboard.description,
                                      tags: dashboard.tags,
                                  },
                              },
                              contextDescription: {
                                  text: dashboard.name,
                                  icon: iconForType('dashboard'),
                              },
                              callback: () => loadDashboard({ action: DashboardLoadAction.Update }),
                          }
                        : undefined
                }
                actions={
                    dashboardMode === DashboardMode.Edit ? (
                        <EditModeActions />
                    ) : dashboardMode === DashboardMode.Fullscreen ? (
                        <FullscreenModeActions />
                    ) : (
                        <ViewModeActions />
                    )
                }
            />
        </>
    )
}
