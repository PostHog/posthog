import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconGridMasonry, IconPlusSmall, IconShare } from '@posthog/icons'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonBadge } from 'lib/lemon-ui/LemonBadge'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu, LemonMenuItem, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { DashboardEventSource, eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { MaxTool } from 'scenes/max/MaxTool'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { AccessControlLevel, AccessControlResourceType, DashboardPlacement, DashboardType } from '~/types'

import { DashboardCustomizeMenu } from 'products/dashboards/frontend/components/DashboardCustomizeMenu/DashboardCustomizeMenu'

import { DashboardCustomizeButton } from './DashboardCustomizeButton'
import { DashboardLoadAction, dashboardLogic } from './dashboardLogic'
import { DashboardSubscribeButton } from './DashboardSubscribeButton'

export function getAddTileMenuItems({
    dashboardWidgetsEnabled,
    onAddInsight,
    onAddText,
    onAddImage,
    onAddButton,
    push,
    setAddWidgetModalOpen,
    onBeforeSelect,
}: {
    dashboardWidgetsEnabled: boolean
    onAddInsight: () => void
    onAddText: () => void
    onAddImage: () => void
    onAddButton: () => void
    push: (url: string) => void
    setAddWidgetModalOpen: (open: boolean) => void
    onBeforeSelect?: () => void
}): LemonMenuItems {
    const withBeforeSelect =
        (onClick: () => void): (() => void) =>
        () => {
            onBeforeSelect?.()
            onClick()
        }

    const contentItems: LemonMenuItem[] = [
        {
            label: 'Charts',
            onClick: withBeforeSelect(onAddInsight),
            'data-attr': 'dashboard-add-insight',
        },
        {
            label: 'Add text',
            onClick: withBeforeSelect(onAddText),
            'data-attr': 'dashboard-add-text-tile',
        },
        {
            label: 'Image',
            tag: 'new' as const,
            onClick: withBeforeSelect(onAddImage),
            'data-attr': 'dashboard-add-image-tile',
        },
        {
            label: 'Button',
            onClick: withBeforeSelect(onAddButton),
            'data-attr': 'dashboard-add-button-tile',
        },
        dashboardWidgetsEnabled
            ? {
                  label: 'Widget',
                  tag: 'new' as const,
                  onClick: withBeforeSelect(() => setAddWidgetModalOpen(true)),
                  'data-attr': 'dashboard-add-widget',
              }
            : {
                  label: 'Widget',
                  tag: 'beta' as const,
                  tooltip: 'Opens settings to enable the Dashboard widgets beta',
                  onClick: withBeforeSelect(() => push(urls.featurePreview(FEATURE_FLAGS.DASHBOARD_WIDGETS))),
                  'data-attr': 'dashboard-add-widget-preview',
              },
    ]

    return [{ title: 'Content', items: contentItems }]
}

export function DashboardAddTileButton(): JSX.Element | null {
    const { dashboard, dashboardWidgetsEnabled, tiles } = useValues(dashboardLogic)
    const {
        loadDashboard,
        setAddWidgetModalOpen,
        openAddInsightModal,
        openTextTileModal,
        openImageTileModal,
        openButtonTileModal,
    } = useActions(dashboardLogic)
    const { push } = useActions(router)
    const { reportDashboardAddMenuOpened } = useActions(eventUsageLogic)

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
                        dashboardWidgetsEnabled,
                        onAddInsight: openAddInsightModal,
                        onAddText: openTextTileModal,
                        onAddImage: openImageTileModal,
                        onAddButton: openButtonTileModal,
                        push,
                        setAddWidgetModalOpen,
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

export function DashboardEditSaveCancelButtons({
    withShortcuts = true,
    applyFiltersButton,
}: {
    withShortcuts?: boolean
    /** The large-dashboard "Apply filters" preview button, rendered between Cancel and Save. */
    applyFiltersButton?: JSX.Element | null
}): JSX.Element {
    const { dashboardLoading, canEditDashboard } = useValues(dashboardLogic)
    const { cancelLayoutEdit, saveLayout } = useActions(dashboardLogic)

    const cancelButton = (
        <LemonButton
            data-attr="dashboard-edit-mode-discard"
            type="secondary"
            onClick={cancelLayoutEdit}
            size="small"
            tooltip="Discard layout changes and exit layout editing"
        >
            Cancel
        </LemonButton>
    )

    const saveButton = (
        <LemonButton
            data-attr="dashboard-edit-mode-save"
            type="primary"
            onClick={saveLayout}
            size="small"
            tooltip="Save dashboard layout"
            tooltipPlacement="bottom"
            disabledReason={
                dashboardLoading
                    ? 'Wait for dashboard to finish loading'
                    : canEditDashboard
                      ? undefined
                      : 'Not privileged to edit this dashboard'
            }
        >
            Save layout
        </LemonButton>
    )

    if (!withShortcuts) {
        return (
            <>
                {cancelButton}
                {applyFiltersButton}
                {saveButton}
            </>
        )
    }

    return (
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
            {applyFiltersButton}
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
    )
}

export function EditModeActions(): JSX.Element {
    const { canEditDashboard, layoutEditMode, tiles, dashboardCustomizeMenuOpen } = useValues(dashboardLogic)
    const { setDashboardCustomizeMenuOpen } = useActions(dashboardLogic)

    return (
        <>
            <DashboardSubscribeButton />
            {layoutEditMode && <DashboardEditSaveCancelButtons />}
            {canEditDashboard && !layoutEditMode && tiles.length > 0 && <DashboardCustomizeButton />}
            {layoutEditMode && tiles.length > 0 && (
                <LemonMenu
                    items={[{ label: () => <DashboardCustomizeMenu /> }]}
                    closeOnClickInside={false}
                    placement="bottom-end"
                    visible={dashboardCustomizeMenuOpen}
                    onVisibilityChange={setDashboardCustomizeMenuOpen}
                >
                    <LemonButton
                        type="secondary"
                        data-attr="dashboard-edit-layout-customize-dropdown"
                        size="small"
                        icon={<IconGridMasonry fontSize="16" />}
                        disabledReason={
                            tiles.length === 0 ? 'Add at least one tile to customize this dashboard' : undefined
                        }
                    >
                        Customize
                    </LemonButton>
                </LemonMenu>
            )}
            <DashboardAddTileButton />
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

export function ViewModeActions(): JSX.Element {
    const { dashboard, canEditDashboard, tiles } = useValues(dashboardLogic)
    if (!dashboard) {
        return <></>
    }

    return (
        <>
            <DashboardSubscribeButton />
            {(tiles.length > 0 || dashboard.is_shared) && <DashboardShareButton dashboard={dashboard} />}
            {canEditDashboard && tiles.length > 0 && <DashboardCustomizeButton />}
            <DashboardAddTileButton />
        </>
    )
}
