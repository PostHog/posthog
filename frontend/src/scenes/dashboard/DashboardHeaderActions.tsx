import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconGridMasonry, IconPlusSmall, IconShare } from '@posthog/icons'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu, LemonMenuItem, LemonMenuItems, LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { DashboardEventSource, eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { MaxTool } from 'scenes/max/MaxTool'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { AccessControlLevel, AccessControlResourceType, DashboardMode } from '~/types'

import { DashboardCustomizeMenu } from 'products/dashboards/frontend/components/DashboardCustomizeMenu/DashboardCustomizeMenu'

import { DashboardLoadAction, dashboardLogic } from './dashboardLogic'
import { DashboardSubscribeButton } from './DashboardSubscribeButton'

export function getAddTileMenuItems({
    dashboardId,
    dashboardWidgetsEnabled,
    onAddInsight,
    push,
    setAddWidgetModalOpen,
    onBeforeSelect,
}: {
    dashboardId: number
    dashboardWidgetsEnabled: boolean
    onAddInsight: () => void
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
            onClick: withBeforeSelect(() => push(urls.dashboardTextTile(dashboardId, 'new'))),
            'data-attr': 'dashboard-add-text-tile',
        },
        {
            label: 'Button',
            onClick: withBeforeSelect(() => push(urls.dashboardButtonTile(dashboardId, 'new'))),
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
    const { loadDashboard, setAddWidgetModalOpen, setPendingInsertion, openAddInsightModal } =
        useActions(dashboardLogic)
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
                        dashboardId: dashboard.id,
                        dashboardWidgetsEnabled,
                        onAddInsight: openAddInsightModal,
                        push,
                        setAddWidgetModalOpen,
                        // Adding from the header appends at the bottom; drop any stale inline-insertion target.
                        onBeforeSelect: () => setPendingInsertion(null),
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
    const { setDashboardMode, cancelEditMode } = useActions(dashboardLogic)

    const cancelButton = (
        <LemonButton
            data-attr="dashboard-edit-mode-discard"
            type="secondary"
            onClick={() => cancelEditMode()}
            size="small"
            tooltip="Discard changes and exit edit mode"
        >
            Cancel
        </LemonButton>
    )

    const saveButton = (
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
                intent="Save dashboard"
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
    const { layoutEditMode, tiles, dashboardCustomizeMenuOpen } = useValues(dashboardLogic)
    const { setDashboardCustomizeMenuOpen } = useActions(dashboardLogic)
    const dashboardCustomizationEnabled = useFeatureFlag('DASHBOARD_CUSTOMIZATION')

    return (
        <>
            <DashboardSubscribeButton />
            {layoutEditMode && <DashboardEditSaveCancelButtons />}
            {dashboardCustomizationEnabled && tiles.length > 0 && (
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

export function ViewModeActions(): JSX.Element {
    const { dashboard, canEditDashboard, tiles } = useValues(dashboardLogic)
    const { setDashboardMode } = useActions(dashboardLogic)
    const dashboardCustomizationEnabled = useFeatureFlag('DASHBOARD_CUSTOMIZATION')
    const { push } = useActions(router)
    if (!dashboard) {
        return <></>
    }

    const sharingDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.SharingConfiguration,
        AccessControlLevel.Viewer
    )

    return (
        <>
            <DashboardSubscribeButton />
            {tiles.length > 0 && (
                <LemonButton
                    type="secondary"
                    data-attr="dashboard-share-button"
                    onClick={() => push(urls.dashboardSharing(dashboard.id))}
                    size="small"
                    icon={<IconShare fontSize="16" />}
                    disabledReason={sharingDisabledReason ?? undefined}
                >
                    Share
                </LemonButton>
            )}
            {canEditDashboard && tiles.length > 0 && (
                <Shortcut
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
                        tooltip="Customize dashboard"
                        tooltipPlacement="top"
                        sideAction={
                            dashboardCustomizationEnabled
                                ? {
                                      'data-attr': 'dashboard-edit-layout-customize-dropdown',
                                      dropdown: {
                                          closeOnClickInside: false,
                                          placement: 'bottom-end',
                                          overlay: (
                                              <LemonMenuOverlay items={[{ label: () => <DashboardCustomizeMenu /> }]} />
                                          ),
                                      },
                                  }
                                : undefined
                        }
                    >
                        Customize
                    </LemonButton>
                </Shortcut>
            )}
            <DashboardAddTileButton />
        </>
    )
}
