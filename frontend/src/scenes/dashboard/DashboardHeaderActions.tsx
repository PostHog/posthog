import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconGridMasonry, IconPlusSmall, IconShare } from '@posthog/icons'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
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
            <AppShortcut
                name="CancelDashboardEdit"
                keybind={[keyBinds.escape]}
                intent="Cancel edit mode"
                interaction="click"
                scope={Scene.Dashboard}
            >
                <LemonButton
                    data-attr="dashboard-edit-mode-discard"
                    type="secondary"
                    onClick={() => setDashboardMode(null, DashboardEventSource.DashboardHeaderDiscardChanges)}
                    size="small"
                    tooltip="Discard changes and exit edit mode"
                >
                    Cancel
                </LemonButton>
            </AppShortcut>
            <AppShortcut
                name="SaveDashboard"
                keybind={[keyBinds.edit, keyBinds.save]}
                intent="Save dashboard"
                interaction="click"
                scope={Scene.Dashboard}
                disabled={!canEditDashboard}
            >
                <LemonButton
                    data-attr="dashboard-edit-mode-save"
                    type="primary"
                    onClick={() => setDashboardMode(null, DashboardEventSource.DashboardHeaderSaveDashboard)}
                    size="small"
                    tooltip="Save dashboard"
                    tooltipPlacement="bottom"
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
            >
                Share
            </LemonButton>
            {canEditDashboard && (
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
                        icon={<IconGridMasonry fontSize="16" />}
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
                    <LemonMenu
                        items={[
                            {
                                label: 'Insight',
                                onClick: showAddInsightToDashboardModal,
                                'data-attr': 'dashboard-add-insight',
                            },
                            {
                                label: 'Text card',
                                onClick: () => push(urls.dashboardTextTile(dashboard.id, 'new')),
                                'data-attr': 'dashboard-add-text-tile',
                            },
                            {
                                label: 'Button',
                                onClick: () => push(urls.dashboardButtonTile(dashboard.id, 'new')),
                                'data-attr': 'dashboard-add-button-tile',
                            },
                        ]}
                    >
                        <LemonButton
                            type="primary"
                            data-attr="dashboard-add-tile"
                            size="small"
                            icon={<IconPlusSmall />}
                        >
                            Add...
                        </LemonButton>
                    </LemonMenu>
                </AccessControlAction>
            </MaxTool>
        </>
    )
}
