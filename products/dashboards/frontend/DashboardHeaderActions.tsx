import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconPlusSmall, IconShare } from '@posthog/icons'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LemonBadge } from 'lib/lemon-ui/LemonBadge'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu, LemonMenuItem, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { reportDashboardAddMenuOpened } from 'scenes/dashboard/dashboardEvents'
import { DashboardLoadAction, dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { MaxTool } from 'scenes/max/MaxTool'
import { urls } from 'scenes/urls'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { AccessControlLevel, AccessControlResourceType, DashboardPlacement, DashboardType } from '~/types'

import {
    ADD_TILE_MENU_DATA_ATTRS,
    DashboardAddTileHandlers,
    DashboardAddTileOption,
    getDashboardAddTileOptions,
    groupDashboardAddTileOptions,
} from './dashboardAddTileOptions'
import { DashboardCustomizeButton } from './DashboardCustomizeButton'
import { DashboardLayoutUndoButton } from './DashboardLayoutUndoButton'
import { DashboardShortcuts } from './DashboardShortcuts'
import { DashboardSubscribeButton } from './DashboardSubscribeButton'

export function getAddTileMenuItems({
    onBeforeSelect,
    ...handlers
}: DashboardAddTileHandlers & { onBeforeSelect?: () => void }): LemonMenuItems {
    const toItem = (option: DashboardAddTileOption): LemonMenuItem => ({
        label: option.label,
        tag: option.tag,
        onClick: () => {
            onBeforeSelect?.()
            option.onClick()
        },
        'data-attr': ADD_TILE_MENU_DATA_ATTRS[option.key],
    })

    return groupDashboardAddTileOptions(getDashboardAddTileOptions(handlers)).map(({ title, options }) => ({
        title,
        items: options.map(toItem),
    }))
}

export function DashboardAddTileButton(): JSX.Element | null {
    const { dashboard, tiles, tileGroupSectionsEnabled } = useValues(dashboardLogic)
    const {
        loadDashboard,
        setAddWidgetModalOpen,
        openAddInsightModal,
        openTextTileModal,
        openImageTileModal,
        openButtonTileModal,
        addTileGroup,
    } = useActions(dashboardLogic)

    if (!dashboard || tiles.length === 0) {
        return null
    }

    return (
        <MaxTool
            className="shrink-0"
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
                    items={getAddTileMenuItems({
                        onAddInsight: openAddInsightModal,
                        onAddText: openTextTileModal,
                        onAddImage: openImageTileModal,
                        onAddButton: openButtonTileModal,
                        setAddWidgetModalOpen,
                        onAddGroup: tileGroupSectionsEnabled ? () => addTileGroup() : undefined,
                    })}
                    onVisibilityChange={(visible) => {
                        if (visible) {
                            reportDashboardAddMenuOpened('header', dashboard.id)
                        }
                    }}
                >
                    <LemonButton type="primary" data-attr="dashboard-add-tile" size="small" icon={<IconPlusSmall />}>
                        Add
                    </LemonButton>
                </LemonMenu>
            </AccessControlAction>
        </MaxTool>
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

export function DashboardShareButton({ dashboard }: { dashboard: DashboardType }): JSX.Element {
    const { push } = useActions(router)
    const sharingDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.SharingConfiguration,
        AccessControlLevel.Viewer
    )

    return (
        <LemonButton
            type="secondary"
            data-attr="dashboard-share-button"
            onClick={() => push(urls.dashboardSharing(dashboard.id))}
            size="small"
            icon={dashboard.is_shared ? <LemonBadge content="On" size="small" /> : <IconShare fontSize="16" />}
            active={dashboard.is_shared}
            disabledReason={sharingDisabledReason ?? undefined}
        >
            {dashboard.is_shared ? 'Sharing' : 'Share'}
        </LemonButton>
    )
}

export function DashboardEmbeddedShareButton({
    dashboard,
    placement,
}: {
    dashboard: DashboardType | null
    placement: DashboardPlacement
}): JSX.Element | null {
    if (
        !dashboard?.is_shared ||
        ![DashboardPlacement.ProjectHomepage, DashboardPlacement.Builtin].includes(placement)
    ) {
        return null
    }

    return (
        <div className="flex justify-end mb-2">
            <DashboardShareButton dashboard={dashboard} />
        </div>
    )
}

export function DashboardActions(): JSX.Element {
    const { dashboard, dashboardEditing, canEditDashboard, tiles } = useValues(dashboardLogic)
    if (!dashboard) {
        return <></>
    }

    return (
        <>
            <DashboardSubscribeButton />
            <DashboardLayoutUndoButton />
            <DashboardShortcuts />
            {!dashboardEditing && (tiles.length > 0 || dashboard.is_shared) && (
                <DashboardShareButton dashboard={dashboard} />
            )}
            {canEditDashboard && tiles.length > 0 && <DashboardCustomizeButton />}
            <DashboardAddTileButton />
        </>
    )
}
