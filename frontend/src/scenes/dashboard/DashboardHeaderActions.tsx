import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconPencil, IconPlusSmall, IconShare } from '@posthog/icons'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { MaxTool } from 'scenes/max/MaxTool'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { AccessControlLevel, AccessControlResourceType, DashboardMode } from '~/types'

import { addInsightToDashboardLogic } from './addInsightToDashboardModalLogic'
import { DashboardLoadAction, dashboardLogic } from './dashboardLogic'

export function EditModeActions(): JSX.Element {
    const { dashboardLoading, canEditDashboard } = useValues(dashboardLogic)
    const { setDashboardMode } = useActions(dashboardLogic)

    return (
        <>
            <LemonButton
                data-attr="dashboard-edit-mode-discard"
                type="secondary"
                onClick={() => setDashboardMode(null, DashboardEventSource.DashboardHeaderDiscardChanges)}
                size="small"
            >
                Cancel
            </LemonButton>
            <AppShortcut
                name="SaveDashboard"
                keybind={[keyBinds.save]}
                intent="Save dashboard"
                interaction="click"
                scope={Scene.Dashboard}
            >
                <LemonButton
                    data-attr="dashboard-edit-mode-save"
                    type="primary"
                    onClick={() => setDashboardMode(null, DashboardEventSource.DashboardHeaderSaveDashboard)}
                    size="small"
                    disabledReason={
                        dashboardLoading
                            ? 'Wait for dashboard to finish loading'
                            : canEditDashboard
                              ? undefined
                              : 'Not privileged to edit this dashboard'
                    }
                >
                    Save
                </LemonButton>
            </AppShortcut>
        </>
    )
}

export function FullscreenModeActions(): JSX.Element {
    const { dashboardLoading } = useValues(dashboardLogic)
    const { setDashboardMode } = useActions(dashboardLogic)

    return (
        <LemonButton
            type="secondary"
            onClick={() => setDashboardMode(null, DashboardEventSource.DashboardHeaderExitFullscreen)}
            data-attr="dashboard-exit-presentation-mode"
            disabled={dashboardLoading}
            size="small"
        >
            Exit full screen
        </LemonButton>
    )
}

export function ViewModeActions(): JSX.Element {
    const { dashboard, canEditDashboard } = useValues(dashboardLogic)
    const { setDashboardMode, loadDashboard } = useActions(dashboardLogic)
    const { showAddInsightToDashboardModal } = useActions(addInsightToDashboardLogic)
    const { push } = useActions(router)
    const hasTileRedesign = useFeatureFlag('DASHBOARD_TILE_REDESIGN')

    if (!dashboard) {
        return <></>
    }

    return (
        <>
            <LemonButton
                type="secondary"
                data-attr="dashboard-share-button"
                onClick={() => push(urls.dashboardSharing(dashboard.id))}
                size="small"
                icon={<IconShare fontSize="16" />}
                tooltip="Share"
                tooltipPlacement="top"
            />
            <AccessControlAction
                resourceType={AccessControlResourceType.Dashboard}
                minAccessLevel={AccessControlLevel.Editor}
                userAccessLevel={dashboard.user_access_level}
            >
                <AppShortcut
                    name="AddTextTileToDashboard"
                    scope={Scene.Dashboard}
                    keybind={[keyBinds.dashboardAddTextTile]}
                    intent="Add text card"
                    interaction="click"
                >
                    <LemonButton
                        onClick={() => {
                            push(urls.dashboardTextTile(dashboard.id, 'new'))
                        }}
                        data-attr="add-text-tile-to-dashboard"
                        type="secondary"
                        size="small"
                        tooltip="Add text card"
                        tooltipPlacement="top"
                        icon={<IconPlusSmall />}
                    >
                        Text card
                    </LemonButton>
                </AppShortcut>
            </AccessControlAction>
            {canEditDashboard && hasTileRedesign && (
                <AppShortcut
                    name="EnterEditMode"
                    scope={Scene.Dashboard}
                    keybind={[keyBinds.edit]}
                    intent="Enter edit mode"
                    interaction="click"
                >
                    <LemonButton
                        type="secondary"
                        data-attr="dashboard-edit-mode-button"
                        onClick={() => setDashboardMode(DashboardMode.Edit, DashboardEventSource.SceneCommonButtons)}
                        size="small"
                        icon={<IconPencil fontSize="16" />}
                        tooltip="Edit layout"
                        tooltipPlacement="top"
                    >
                        Edit layout
                    </LemonButton>
                </AppShortcut>
            )}
            <MaxTool
                identifier="upsert_dashboard"
                context={{
                    current_dashboard: {
                        id: dashboard.id,
                        name: dashboard.name,
                        description: dashboard.description,
                        tags: dashboard.tags,
                    },
                }}
                contextDescription={{
                    text: dashboard.name,
                    icon: iconForType('dashboard'),
                }}
                active={false}
                callback={() => loadDashboard({ action: DashboardLoadAction.Update })}
                position="top-right"
            >
                <AccessControlAction
                    resourceType={AccessControlResourceType.Dashboard}
                    minAccessLevel={AccessControlLevel.Editor}
                    userAccessLevel={dashboard.user_access_level}
                >
                    <LemonButton
                        onClick={showAddInsightToDashboardModal}
                        type="primary"
                        data-attr="dashboard-add-graph-header"
                        size="small"
                    >
                        Add insight
                    </LemonButton>
                </AccessControlAction>
            </MaxTool>
        </>
    )
}
