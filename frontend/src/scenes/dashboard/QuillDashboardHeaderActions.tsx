import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconGridMasonry, IconShare } from '@posthog/icons'
import { Badge, Button, Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType, DashboardMode } from '~/types'

import { DashboardCustomizeMenu } from 'products/dashboards/frontend/components/DashboardCustomizeMenu/DashboardCustomizeMenu'

import { dashboardLogic } from './dashboardLogic'
import { QuillDashboardAddTileButton } from './QuillDashboardAddTileButton'
import { QuillDashboardCustomizeButton } from './QuillDashboardCustomizeButton'
import { QuillDashboardSubscribeButton } from './QuillDashboardSubscribeButton'

export function QuillDashboardHeaderActions(): JSX.Element | null {
    const {
        dashboard,
        dashboardEditing,
        dashboardMode,
        dashboardLoading,
        canEditDashboard,
        layoutEditMode,
        tiles,
        dashboardCustomizeMenuOpen,
        showTextTileModal,
        showImageTileModal,
        showButtonTileModal,
        addWidgetModalOpen,
    } = useValues(dashboardLogic)
    const { setDashboardMode, setDashboardCustomizeMenuOpen, cancelLayoutEdit, saveLayout } = useActions(dashboardLogic)
    const { push } = useActions(router)

    if (!dashboard) {
        return null
    }

    if (dashboardEditing) {
        const withShortcuts = !(showTextTileModal || showImageTileModal || showButtonTileModal || addWidgetModalOpen)
        const cancelButton = (
            <Button
                data-attr="dashboard-edit-mode-discard"
                variant="outline"
                onClick={cancelLayoutEdit}
                tooltip="Discard layout changes and exit layout editing"
            >
                Cancel
            </Button>
        )
        const saveButton = (
            <Button
                data-attr="dashboard-edit-mode-save"
                variant="primary"
                onClick={saveLayout}
                tooltip="Save dashboard layout"
                disabledReason={
                    dashboardLoading
                        ? 'Wait for dashboard to finish loading'
                        : canEditDashboard
                          ? undefined
                          : 'Not privileged to edit this dashboard'
                }
            >
                Save layout
            </Button>
        )

        return (
            <>
                <QuillDashboardSubscribeButton />
                {layoutEditMode &&
                    (withShortcuts ? (
                        <>
                            <Shortcut
                                name="CancelDashboardEdit"
                                keybind={[keyBinds.escape]}
                                intent="Cancel edit mode"
                                interaction="click"
                                scope={Scene.Dashboard}
                            >
                                {cancelButton}
                            </Shortcut>
                            <Shortcut
                                name="SaveDashboard"
                                keybind={[keyBinds.edit, keyBinds.save]}
                                intent="Save dashboard layout"
                                interaction="click"
                                scope={Scene.Dashboard}
                                disabled={!canEditDashboard}
                            >
                                {saveButton}
                            </Shortcut>
                        </>
                    ) : (
                        <>
                            {cancelButton}
                            {saveButton}
                        </>
                    ))}
                {canEditDashboard && !layoutEditMode && tiles.length > 0 && <QuillDashboardCustomizeButton />}
                {layoutEditMode && tiles.length > 0 && (
                    <Popover open={dashboardCustomizeMenuOpen} onOpenChange={setDashboardCustomizeMenuOpen}>
                        <PopoverTrigger
                            render={<Button variant="outline" data-attr="dashboard-edit-layout-customize-dropdown" />}
                        >
                            <IconGridMasonry />
                            Customize
                        </PopoverTrigger>
                        <PopoverContent align="end" className="w-auto p-0">
                            <DashboardCustomizeMenu />
                        </PopoverContent>
                    </Popover>
                )}
                <QuillDashboardAddTileButton />
            </>
        )
    }

    if (dashboardMode === DashboardMode.Fullscreen) {
        return (
            <Button
                variant="outline"
                onClick={() => setDashboardMode(null, DashboardEventSource.DashboardHeaderExitFullscreen)}
                data-attr="dashboard-exit-presentation-mode"
                disabled={dashboardLoading}
            >
                Exit full screen
            </Button>
        )
    }

    const sharingDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.SharingConfiguration,
        AccessControlLevel.Viewer
    )

    return (
        <>
            <QuillDashboardSubscribeButton />
            {(tiles.length > 0 || dashboard.is_shared) && (
                <Button
                    variant="outline"
                    data-attr="dashboard-share-button"
                    onClick={() => push(urls.dashboardSharing(dashboard.id))}
                    disabledReason={sharingDisabledReason}
                >
                    {dashboard.is_shared ? <Badge variant="success">On</Badge> : <IconShare />}
                    <span>{dashboard.is_shared ? 'Sharing' : 'Share'}</span>
                </Button>
            )}
            {canEditDashboard && tiles.length > 0 && <QuillDashboardCustomizeButton />}
            <QuillDashboardAddTileButton />
        </>
    )
}
