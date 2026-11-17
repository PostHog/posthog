import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import {
    IconBell,
    IconCode2,
    IconCopy,
    IconDownload,
    IconGraph,
    IconKeyboard,
    IconNotebook,
    IconPalette,
    IconPlusSmall,
    IconPulse,
    IconScreen,
    IconShare,
    IconTrash,
    IconRedo,
    IconUndo,
} from '@posthog/icons'
import { Button } from '@posthog/quill'

import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { metalyticsLogic } from 'lib/components/Metalytics/metalyticsLogic'
import { SceneTagsCombobox } from 'lib/components/Scenes/SceneTagsCombobox'
import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'
import { useSceneFileActions } from 'lib/components/Scenes/useSceneFileActions'
import { RenderKeybind } from 'lib/components/Shortcuts/RenderKeybind'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getAccessControlDisabledReason, userHasAccess } from 'lib/utils/accessControlUtils'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { slugify } from 'lib/utils/strings'
import { AnalyticsCollectionDialogHost } from 'scenes/analytics/AnalyticsCollectionDialogHost'
import { ShareToSpaceTarget } from 'scenes/analytics/analyticsShareLogic'
import { useAnalyticsCollectionActions } from 'scenes/analytics/useAnalyticsCollectionActions'
import { useScenePinAction } from 'scenes/analytics/useScenePinAction'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { dashboardTemplateForExport } from 'scenes/dashboard/dashboardUtils'
import { interProjectCopyLogic } from 'scenes/resource-transfer/interProjectCopyLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { sceneLayoutLogic } from '~/layout/scenes/sceneLayoutLogic'
import { notebooksModel } from '~/models/notebooksModel'
import { AccessControlLevel, AccessControlResourceType, DashboardMode, ExporterFormat, SidePanelTab } from '~/types'

import { urlForSubscriptions } from 'products/subscriptions/frontend/components/Subscriptions/utils'

import { dashboardInsightColorsModalLogic } from './dashboardInsightColorsModalLogic'
import { dashboardTemplateModalLogic } from './dashboards/templates/dashboardTemplateModalLogic'
import { DashboardShortcutsList } from './DashboardShortcutsList'
import { deleteDashboardLogic } from './deleteDashboardLogic'
import { duplicateDashboardLogic } from './duplicateDashboardLogic'
import { useDashboardAddTileAction } from './useDashboardAddTileAction'
import { useDashboardCustomizeAction } from './useDashboardCustomizeAction'

const RESOURCE_TYPE = 'dashboard'

export function DashboardSceneMenuBar(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]) {
        return null
    }
    return <DashboardSceneMenuBarInner />
}

function DashboardSceneMenuBarInner(): JSX.Element | null {
    const {
        dashboard,
        dashboardMode,
        canEditDashboard,
        isSavingTags,
        isPinned,
        asDashboardTemplate,
        canSaveProjectDashboardTemplate,
        effectiveEditBarFilters,
        currentDashboardVariables,
        tiles,
        apiUrl,
        undoLayoutDisabledReason,
        redoLayoutDisabledReason,
        canUndoLayoutChange,
        canEditLayout,
    } = useValues(dashboardLogic)
    const {
        setDashboardMode,
        updateDashboardTags,
        togglePinned,
        setTerraformModalOpen,
        undoLayoutChange,
        redoLayoutChange,
    } = useActions(dashboardLogic)
    const { startExport } = useActions(exportsLogic)
    const { createNotebookFromDashboard } = useActions(notebooksModel)
    const { showInsightColorsModal } = useActions(dashboardInsightColorsModalLogic)
    const { setScenePanelOpen } = useActions(sceneLayoutLogic)
    const { showDuplicateDashboardModal } = useActions(duplicateDashboardLogic)
    const { showDeleteDashboardModal } = useActions(deleteDashboardLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { instanceId: metalyticsInstanceId } = useValues(metalyticsLogic)

    const { user } = useValues(userLogic)
    const { canCopyToProject } = useValues(interProjectCopyLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const hasDashboardColors = !!featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_DASHBOARD_COLORS]
    const showMetalytics = dashboard != null && metalyticsInstanceId != null && !!featureFlags[FEATURE_FLAGS.METALYTICS]

    const { push } = useActions(router)
    // Collections exist only in the Today navigation.
    const collectionTarget: ShareToSpaceTarget | null =
        dashboard && featureFlags[FEATURE_FLAGS.TODAY_RAIL_NAV]
            ? { type: 'dashboard', ref: String(dashboard.id), name: dashboard.name || 'Untitled dashboard' }
            : null
    const addTileAction = useDashboardAddTileAction()
    const customizeActions = useDashboardCustomizeAction()
    const fileActions = useSceneFileActions(RESOURCE_TYPE, { section: 'project' })
    const collectionActions = useAnalyticsCollectionActions(collectionTarget, RESOURCE_TYPE, { section: 'project' })
    const pinActions = useScenePinAction(RESOURCE_TYPE)

    if (!dashboard) {
        return null
    }

    // Creating an export requires editor access to the export resource.
    const sharingDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.SharingConfiguration,
        AccessControlLevel.Viewer
    )
    const exportAccessControlDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Export,
        AccessControlLevel.Editor
    )
    const customerTemplateEditorAccess = userHasAccess(AccessControlResourceType.Dashboard, AccessControlLevel.Editor)
    const customerTemplateDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Dashboard,
        AccessControlLevel.Editor,
        undefined,
        true
    )
    const missingTemplatePayload = !asDashboardTemplate
    const saveTemplateDisabled = !customerTemplateEditorAccess || missingTemplatePayload
    const saveTemplateTooltip = !customerTemplateEditorAccess
        ? (customerTemplateDisabledReason ?? 'You need edit access to dashboard templates to save a template.')
        : missingTemplatePayload
          ? 'Template data is not ready yet. Try again in a moment.'
          : undefined

    const exitFullscreen = dashboardMode === DashboardMode.Fullscreen
    const subscribe = (): void => {
        posthog.capture('dashboard subscribe clicked', { dashboard_id: dashboard.id })
        push(urlForSubscriptions({ dashboardId: dashboard.id }))
    }
    const openInsightsInNewTabs = (): void => {
        tiles.forEach((tile) => {
            if (tile.insight?.short_id == null) {
                return
            }
            newInternalTab(
                urls.insightView(
                    tile.insight.short_id,
                    dashboard.id,
                    currentDashboardVariables,
                    effectiveEditBarFilters,
                    tile?.filters_overrides
                )
            )
        })
        setScenePanelOpen(false)
    }
    const deleteDisabledReason =
        getAccessControlDisabledReason(
            AccessControlResourceType.Dashboard,
            AccessControlLevel.Editor,
            dashboard.user_access_level
        ) ?? undefined
    // A full-screen dashboard keeps only its exit in the title row.
    const pin = (pinned: SceneAction['pinned']): SceneAction['pinned'] => (exitFullscreen ? undefined : pinned)

    const actions: SceneAction[] = [
        ...(canEditDashboard
            ? ([
                  {
                      group: 'file',
                      section: 'create',
                      type: 'submenu',
                      id: `${RESOURCE_TYPE}-menubar-create`,
                      label: 'Create',
                      icon: <IconPlusSmall />,
                      items: [
                          {
                              id: `${RESOURCE_TYPE}-menubar-create-notebook`,
                              label: 'Notebook from dashboard',
                              icon: <IconNotebook />,
                              onSelect: () => createNotebookFromDashboard(dashboard),
                          },
                      ],
                  },
              ] satisfies SceneAction[])
            : []),
        ...(canEditDashboard && tiles.length > 0
            ? [
                  { ...addTileAction, pinned: pin({ order: 1, variant: 'primary', dataAttr: 'dashboard-add-tile' }) },
                  ...customizeActions,
              ]
            : []),
        ...(canEditDashboard && tiles.length > 0
            ? ([
                  {
                      group: 'file',
                      section: 'share',
                      id: `${RESOURCE_TYPE}-menubar-subscribe`,
                      label: 'Subscribe',
                      icon: <IconBell />,
                      onSelect: subscribe,
                      pinned: pin({ order: 2, variant: 'secondary', dataAttr: 'dashboard-subscribe-prominent-button' }),
                  },
              ] satisfies SceneAction[])
            : []),
        ...(tiles.length > 0 || dashboard.is_shared
            ? ([
                  {
                      group: 'file',
                      section: 'share',
                      id: `${RESOURCE_TYPE}-menubar-share`,
                      label: dashboard.is_shared ? 'Sharing settings' : 'Share or embed',
                      icon: <IconShare />,
                      disabledReason: sharingDisabledReason ?? undefined,
                      onSelect: () => push(urls.dashboardSharing(dashboard.id)),
                      pinned: pin({ order: 3, variant: 'secondary', dataAttr: 'dashboard-share-button' }),
                  },
              ] satisfies SceneAction[])
            : []),
        ...fileActions,
        ...collectionActions,
        ...(canCopyToProject
            ? ([
                  {
                      group: 'file',
                      section: 'project',
                      id: `${RESOURCE_TYPE}-menubar-copy-to-project`,
                      label: 'Copy to another project',
                      icon: <IconCopy />,
                      onSelect: () => push(urls.resourceTransfer('Dashboard', dashboard.id)),
                  },
              ] satisfies SceneAction[])
            : []),
        {
            group: 'file',
            section: 'project',
            id: `${RESOURCE_TYPE}-menubar-terraform`,
            label: 'Manage with Terraform',
            icon: <IconCode2 />,
            opensFloatingUi: true,
            onSelect: () => setTerraformModalOpen(true),
        },
        {
            group: 'file',
            section: 'project',
            id: `${RESOURCE_TYPE}-menubar-open-insights`,
            label: 'Open insights in new tabs',
            icon: <IconGraph />,
            disabledReason: tiles.length === 0 ? 'Dashboard has no insights' : undefined,
            onSelect: openInsightsInNewTabs,
        },
        ...(canEditDashboard
            ? ([
                  {
                      group: 'file',
                      section: 'project',
                      type: 'submenu',
                      id: `${RESOURCE_TYPE}-menubar-export`,
                      label: 'Export',
                      icon: <IconDownload />,
                      items: [
                          {
                              id: `${RESOURCE_TYPE}-menubar-export-png`,
                              label: 'PNG',
                              icon: <IconDownload />,
                              disabledReason: exportAccessControlDisabledReason ?? undefined,
                              onSelect: () =>
                                  startExport({
                                      export_format: ExporterFormat.PNG,
                                      dashboard: dashboard.id,
                                      export_context: {
                                          path: apiUrl(),
                                          variables_override: currentDashboardVariables,
                                      },
                                  }),
                          },
                          ...(user?.is_staff
                              ? [
                                    {
                                        id: `${RESOURCE_TYPE}-menubar-export-json`,
                                        label: 'JSON (staff)',
                                        icon: <IconDownload />,
                                        onSelect: () =>
                                            startExport({
                                                export_format: ExporterFormat.JSON,
                                                export_context: {
                                                    localData: JSON.stringify(
                                                        dashboardTemplateForExport(asDashboardTemplate)
                                                    ),
                                                    filename: `dashboard-${slugify(
                                                        dashboard?.name || 'nameless dashboard'
                                                    )}.json`,
                                                    mediaType: ExporterFormat.JSON,
                                                },
                                            }),
                                    },
                                ]
                              : []),
                      ],
                  },
              ] satisfies SceneAction[])
            : []),
        ...(canEditDashboard
            ? ([
                  {
                      group: 'file',
                      section: 'delete',
                      id: `${RESOURCE_TYPE}-menubar-delete`,
                      label: 'Delete dashboard',
                      icon: <IconTrash />,
                      destructive: true,
                      disabledReason: deleteDisabledReason,
                      onSelect: () => showDeleteDashboardModal(dashboard.id),
                  },
                  {
                      group: 'edit',
                      section: 'history',
                      id: `${RESOURCE_TYPE}-menubar-undo-layout`,
                      label: 'Undo layout change',
                      icon: <IconUndo />,
                      disabledReason: undoLayoutDisabledReason ?? undefined,
                      shortcut: <RenderKeybind keybind={[keyBinds.undo]} minimal />,
                      onSelect: () => undoLayoutChange(),
                      pinned:
                          canUndoLayoutChange && canEditLayout
                              ? pin({ order: 0, variant: 'icon', dataAttr: 'dashboard-layout-undo' })
                              : undefined,
                  },
                  {
                      group: 'edit',
                      section: 'history',
                      id: `${RESOURCE_TYPE}-menubar-redo-layout`,
                      label: 'Redo layout change',
                      icon: <IconRedo />,
                      disabledReason: redoLayoutDisabledReason ?? undefined,
                      shortcut: <RenderKeybind keybind={[keyBinds.redo]} minimal />,
                      onSelect: () => redoLayoutChange(),
                  },
              ] satisfies SceneAction[])
            : []),
        {
            group: 'edit',
            id: `${RESOURCE_TYPE}-menubar-duplicate`,
            label: 'Duplicate',
            icon: <IconCopy />,
            opensFloatingUi: true,
            onSelect: () => showDuplicateDashboardModal(dashboard.id, dashboard.name),
        },
        ...(canEditDashboard && hasDashboardColors && tiles.length > 0
            ? ([
                  {
                      group: 'edit',
                      id: `${RESOURCE_TYPE}-menubar-customize-colors`,
                      label: 'Customize colors',
                      icon: <IconPalette />,
                      opensFloatingUi: true,
                      onSelect: () => showInsightColorsModal(dashboard.id),
                  },
              ] satisfies SceneAction[])
            : []),
        ...(canSaveProjectDashboardTemplate
            ? ([
                  {
                      group: 'edit',
                      id: `${RESOURCE_TYPE}-menubar-save-as-template`,
                      label: 'Save as dashboard template',
                      icon: <IconScreen />,
                      opensFloatingUi: true,
                      disabledReason: saveTemplateDisabled ? saveTemplateTooltip : undefined,
                      onSelect: () => {
                          if (asDashboardTemplate) {
                              dashboardTemplateModalLogic.actions.openCreate(asDashboardTemplate)
                          }
                      },
                  },
              ] satisfies SceneAction[])
            : []),
        ...pinActions,
        {
            group: 'edit',
            section: 'toggles',
            type: 'checkbox',
            id: `${RESOURCE_TYPE}-menubar-pin`,
            label: 'Pinned',
            checked: isPinned,
            onCheckedChange: () => togglePinned(),
        },
        {
            group: 'edit',
            section: 'toggles',
            type: 'checkbox',
            id: `${RESOURCE_TYPE}-menubar-fullscreen`,
            label: exitFullscreen ? 'Exit full screen' : 'Fullscreen',
            checked: exitFullscreen,
            onCheckedChange: (checked) =>
                setDashboardMode(checked ? DashboardMode.Fullscreen : null, DashboardEventSource.SceneCommonButtons),
            pinned: exitFullscreen
                ? { order: 0, variant: 'secondary', dataAttr: 'dashboard-exit-presentation-mode' }
                : undefined,
        },
        {
            group: 'view',
            type: 'panel',
            id: `${RESOURCE_TYPE}-menubar-keyboard-shortcuts`,
            label: 'Keyboard shortcuts',
            icon: <IconKeyboard />,
            render: () => <DashboardShortcutsList />,
        },
        {
            group: 'metadata',
            type: 'panel',
            id: `${RESOURCE_TYPE}-menubar-metadata`,
            label: 'Metadata',
            render: () => (
                <>
                    <SceneTagsCombobox
                        onSave={(t) => updateDashboardTags(t)}
                        canEdit={canEditDashboard}
                        tags={dashboard?.tags}
                        dataAttrKey={RESOURCE_TYPE}
                        loading={isSavingTags}
                    />
                    <SceneActivityIndicator at={dashboard?.created_at} by={dashboard?.created_by} prefix="Created" />
                    {showMetalytics && (
                        <Button
                            type="button"
                            left
                            onClick={() => openSidePanel(SidePanelTab.Activity, 'metalytics')}
                            data-attr={`${RESOURCE_TYPE}-menubar-metalytics`}
                        >
                            <IconPulse />
                            View metalytics
                        </Button>
                    )}
                </>
            ),
        },
    ]

    return (
        <>
            <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
            {collectionTarget && <AnalyticsCollectionDialogHost target={collectionTarget} />}
        </>
    )
}
