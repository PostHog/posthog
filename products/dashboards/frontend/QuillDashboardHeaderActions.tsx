import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconShare } from '@posthog/icons'
import { Badge, Button } from '@posthog/quill'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType, DashboardMode } from '~/types'

import { DashboardLayoutUndoButton } from './DashboardLayoutUndoButton'
import { DashboardShortcuts } from './DashboardShortcuts'
import { QuillDashboardAddTileButton } from './QuillDashboardAddTileButton'
import { QuillDashboardCustomizeButton } from './QuillDashboardCustomizeButton'
import { QuillDashboardSubscribeButton } from './QuillDashboardSubscribeButton'

export function QuillDashboardHeaderActions(): JSX.Element | null {
    const { dashboard, dashboardEditing, dashboardMode, dashboardLoading, canEditDashboard, tiles } =
        useValues(dashboardLogic)
    const { setDashboardMode } = useActions(dashboardLogic)
    const { push } = useActions(router)

    if (!dashboard) {
        return null
    }

    if (dashboardMode === DashboardMode.Fullscreen && !dashboardEditing) {
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
            <DashboardLayoutUndoButton />
            <DashboardShortcuts />
            {!dashboardEditing && (tiles.length > 0 || dashboard.is_shared) && (
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
