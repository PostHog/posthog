import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import {
    IconBell,
    IconCode2,
    IconCopy,
    IconDownload,
    IconGraph,
    IconNotebook,
    IconPalette,
    IconPulse,
    IconScreen,
    IconTrash,
} from '@posthog/icons'
import { Button } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { metalyticsLogic } from 'lib/components/Metalytics/metalyticsLogic'
import { SceneMenuBarFileItems } from 'lib/components/Scenes/SceneMenuBarFileItems'
import { SceneTagsCombobox } from 'lib/components/Scenes/SceneTagsCombobox'
import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'
import { urlForSubscriptions } from 'lib/components/Subscriptions/utils'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getAccessControlDisabledReason, userHasAccess } from 'lib/utils/accessControlUtils'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { slugify } from 'lib/utils/strings'
import { deleteDashboardLogic } from 'scenes/dashboard/deleteDashboardLogic'
import { duplicateDashboardLogic } from 'scenes/dashboard/duplicateDashboardLogic'
import { interProjectCopyLogic } from 'scenes/resource-transfer/interProjectCopyLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import {
    SceneMenuBar,
    SceneMenuBarCheckboxItem,
    SceneMenuBarItem,
    SceneMenuBarMenu,
    SceneMenuBarPopover,
    SceneMenuBarSeparator,
    SceneMenuBarSubMenu,
} from '~/layout/scenes/components/SceneMenuBar'
import { sceneLayoutLogic } from '~/layout/scenes/sceneLayoutLogic'
import { notebooksModel } from '~/models/notebooksModel'
import { tagsModel } from '~/models/tagsModel'
import { AccessControlLevel, AccessControlResourceType, DashboardMode, ExporterFormat, SidePanelTab } from '~/types'

import { dashboardInsightColorsModalLogic } from './dashboardInsightColorsModalLogic'
import { dashboardLogic } from './dashboardLogic'
import { dashboardTemplateModalLogic } from './dashboards/templates/dashboardTemplateModalLogic'

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
        effectiveDashboardVariableOverrides,
        tiles,
        apiUrl,
    } = useValues(dashboardLogic)
    const { setDashboardMode, updateDashboardTags, togglePinned, setTerraformModalOpen } = useActions(dashboardLogic)
    const { startExport } = useActions(exportsLogic)
    const { createNotebookFromDashboard } = useActions(notebooksModel)
    const { showInsightColorsModal } = useActions(dashboardInsightColorsModalLogic)
    const { setScenePanelOpen } = useActions(sceneLayoutLogic)
    const { showDuplicateDashboardModal } = useActions(duplicateDashboardLogic)
    const { showDeleteDashboardModal } = useActions(deleteDashboardLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { instanceId: metalyticsInstanceId } = useValues(metalyticsLogic)

    const { user } = useValues(userLogic)
    const { tags } = useValues(tagsModel)
    const { canCopyToProject } = useValues(interProjectCopyLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const hasDashboardColors = !!featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_DASHBOARD_COLORS]
    const showMetalytics = dashboard != null && metalyticsInstanceId != null && !!featureFlags[FEATURE_FLAGS.METALYTICS]

    const { push } = useActions(router)

    if (!dashboard) {
        return null
    }

    const canShowDelete = canEditDashboard
    // Creating an export requires editor access to the export resource.
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

    const openInsightsInNewTabsDisabled =
        dashboardMode === DashboardMode.Edit
            ? 'Cannot open insights when editing dashboard'
            : tiles.length === 0
              ? 'Dashboard has no insights'
              : undefined

    const showCreateMenu = canEditDashboard // notebook + subscribe both gated on canEdit
    const showEditMenu = true // duplicate always
    const showFileMenu = true
    const showMetadataMenu = true

    return (
        <SceneMenuBar>
            {showFileMenu && (
                <SceneMenuBarMenu label="File" dataAttr={`${RESOURCE_TYPE}-menubar-file`}>
                    {showCreateMenu && (
                        <>
                            <SceneMenuBarSubMenu label="Create">
                                <SceneMenuBarItem
                                    onClick={() => createNotebookFromDashboard(dashboard)}
                                    data-attr={`${RESOURCE_TYPE}-menubar-create-notebook`}
                                >
                                    <IconNotebook />
                                    Notebook from dashboard
                                </SceneMenuBarItem>
                                <SceneMenuBarItem
                                    onClick={() => push(urlForSubscriptions({ dashboardId: dashboard.id }))}
                                    data-attr={`${RESOURCE_TYPE}-menubar-subscribe`}
                                >
                                    <IconBell />
                                    Subscription
                                </SceneMenuBarItem>
                            </SceneMenuBarSubMenu>
                            <SceneMenuBarSeparator />
                        </>
                    )}
                    <SceneMenuBarFileItems dataAttrKey={RESOURCE_TYPE} />
                    {canCopyToProject && (
                        <SceneMenuBarItem
                            onClick={() => push(urls.resourceTransfer('Dashboard', dashboard.id))}
                            data-attr={`${RESOURCE_TYPE}-menubar-copy-to-project`}
                        >
                            <IconCopy />
                            Copy to another project
                        </SceneMenuBarItem>
                    )}
                    <SceneMenuBarItem
                        opensFloatingUi
                        onClick={() => setTerraformModalOpen(true)}
                        data-attr={`${RESOURCE_TYPE}-menubar-terraform`}
                    >
                        <IconCode2 />
                        Manage with Terraform
                    </SceneMenuBarItem>
                    <SceneMenuBarItem
                        onClick={() => {
                            tiles.forEach((tile) => {
                                if (tile.insight?.short_id == null) {
                                    return
                                }
                                const url = urls.insightView(
                                    tile.insight.short_id,
                                    dashboard.id,
                                    effectiveDashboardVariableOverrides,
                                    effectiveEditBarFilters,
                                    tile?.filters_overrides
                                )
                                newInternalTab(url)
                            })
                            setScenePanelOpen(false)
                        }}
                        disabled={!!openInsightsInNewTabsDisabled}
                        data-attr={`${RESOURCE_TYPE}-menubar-open-insights`}
                    >
                        <IconGraph />
                        Open insights in new tabs
                    </SceneMenuBarItem>
                    {canEditDashboard && (
                        <SceneMenuBarSubMenu label="Export">
                            <SceneMenuBarItem
                                disabled={!!exportAccessControlDisabledReason}
                                tooltip={exportAccessControlDisabledReason ?? undefined}
                                onClick={() =>
                                    startExport({
                                        export_format: ExporterFormat.PNG,
                                        dashboard: dashboard.id,
                                        export_context: {
                                            path: apiUrl(),
                                            variables_override: effectiveDashboardVariableOverrides,
                                        },
                                    })
                                }
                                data-attr={`${RESOURCE_TYPE}-menubar-export-png`}
                            >
                                <IconDownload />
                                PNG
                            </SceneMenuBarItem>
                            {user?.is_staff && (
                                <SceneMenuBarItem
                                    onClick={() =>
                                        startExport({
                                            export_format: ExporterFormat.JSON,
                                            export_context: {
                                                localData: JSON.stringify(asDashboardTemplate),
                                                filename: `dashboard-${slugify(
                                                    dashboard?.name || 'nameless dashboard'
                                                )}.json`,
                                                mediaType: ExporterFormat.JSON,
                                            },
                                        })
                                    }
                                    data-attr={`${RESOURCE_TYPE}-menubar-export-json`}
                                >
                                    <IconDownload />
                                    JSON (staff)
                                </SceneMenuBarItem>
                            )}
                        </SceneMenuBarSubMenu>
                    )}
                    {canShowDelete && (
                        <>
                            <SceneMenuBarSeparator />
                            <AccessControlAction
                                resourceType={AccessControlResourceType.Dashboard}
                                minAccessLevel={AccessControlLevel.Editor}
                                userAccessLevel={dashboard.user_access_level}
                            >
                                {({ disabledReason }) => (
                                    <SceneMenuBarItem
                                        variant="destructive"
                                        disabled={!!disabledReason}
                                        onClick={() => showDeleteDashboardModal(dashboard.id)}
                                        data-attr={`${RESOURCE_TYPE}-menubar-delete`}
                                    >
                                        <IconTrash />
                                        Delete dashboard
                                    </SceneMenuBarItem>
                                )}
                            </AccessControlAction>
                        </>
                    )}
                </SceneMenuBarMenu>
            )}
            {showEditMenu && (
                <SceneMenuBarMenu label="Edit" dataAttr={`${RESOURCE_TYPE}-menubar-edit`}>
                    <SceneMenuBarItem
                        opensFloatingUi
                        onClick={() => showDuplicateDashboardModal(dashboard.id, dashboard.name)}
                        data-attr={`${RESOURCE_TYPE}-menubar-duplicate`}
                    >
                        <IconCopy />
                        Duplicate
                    </SceneMenuBarItem>
                    {canEditDashboard && hasDashboardColors && (
                        <SceneMenuBarItem
                            opensFloatingUi
                            onClick={() => showInsightColorsModal(dashboard.id)}
                            data-attr={`${RESOURCE_TYPE}-menubar-customize-colors`}
                        >
                            <IconPalette />
                            Customize colors
                        </SceneMenuBarItem>
                    )}
                    {canSaveProjectDashboardTemplate && (
                        <SceneMenuBarItem
                            opensFloatingUi
                            onClick={() => {
                                if (asDashboardTemplate) {
                                    dashboardTemplateModalLogic.actions.openCreate(asDashboardTemplate)
                                }
                            }}
                            disabled={saveTemplateDisabled}
                            tooltip={saveTemplateTooltip}
                            data-attr={`${RESOURCE_TYPE}-menubar-save-as-template`}
                        >
                            <IconScreen />
                            Save as dashboard template
                        </SceneMenuBarItem>
                    )}
                    {/* Toggle group — separated from regular Edit actions */}
                    <SceneMenuBarSeparator />
                    <SceneMenuBarCheckboxItem
                        checked={isPinned}
                        onCheckedChange={() => togglePinned()}
                        data-attr={`${RESOURCE_TYPE}-menubar-pin`}
                    >
                        Pinned
                    </SceneMenuBarCheckboxItem>
                    <SceneMenuBarCheckboxItem
                        checked={dashboardMode === DashboardMode.Fullscreen}
                        onCheckedChange={(checked) => {
                            setDashboardMode(
                                checked ? DashboardMode.Fullscreen : null,
                                DashboardEventSource.SceneCommonButtons
                            )
                        }}
                        data-attr={`${RESOURCE_TYPE}-menubar-fullscreen`}
                    >
                        Fullscreen
                    </SceneMenuBarCheckboxItem>
                </SceneMenuBarMenu>
            )}
            {showMetadataMenu && (
                <SceneMenuBarPopover
                    label="Metadata"
                    dataAttr={`${RESOURCE_TYPE}-menubar-metadata`}
                    contentClassName="w-80 p-2 flex flex-col gap-2"
                >
                    <SceneTagsCombobox
                        onSave={(t) => updateDashboardTags(t)}
                        canEdit={canEditDashboard}
                        tags={dashboard?.tags}
                        tagsAvailable={tags.filter((t) => !dashboard?.tags?.includes(t))}
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
                </SceneMenuBarPopover>
            )}
        </SceneMenuBar>
    )
}
