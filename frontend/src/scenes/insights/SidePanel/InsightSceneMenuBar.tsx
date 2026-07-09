import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import {
    IconBell,
    IconCode2,
    IconCopy,
    IconDownload,
    IconEndpoints,
    IconPencil,
    IconPeople,
    IconPlusSmall,
    IconPulse,
    IconShare,
    IconTrash,
    IconWarning,
} from '@posthog/icons'
import { Button } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { metalyticsLogic } from 'lib/components/Metalytics/metalyticsLogic'
import { SceneMenuBarAddToNotebook } from 'lib/components/Scenes/SceneMenuBarAddToNotebook'
import { SceneMenuBarFileItems } from 'lib/components/Scenes/SceneMenuBarFileItems'
import { SceneTagsCombobox } from 'lib/components/Scenes/SceneTagsCombobox'
import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { NotebookNodeType } from 'scenes/notebooks/types'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
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
import { tagsModel } from '~/models/tagsModel'
import { NodeKind } from '~/queries/schema/schema-general'
import { isDataTableNode, isDataVisualizationNode, isEventsQuery, isHogQLQuery } from '~/queries/utils'
import {
    AccessControlLevel,
    AccessControlResourceType,
    AvailableFeature,
    ExporterFormat,
    InsightLogicProps,
    ItemMode,
    QueryBasedInsightModel,
    SidePanelTab,
} from '~/types'

import { endpointLogic } from 'products/endpoints/frontend/endpointLogic'
import { urlForSubscriptions } from 'products/subscriptions/frontend/components/Subscriptions/utils'

import { insightModalsLogic } from '../insightModalsLogic'
import { openSaveAsCohortDialog } from './insightSidePanelDialogs'

const RESOURCE_TYPE = 'insight'

export function InsightSceneMenuBar({
    insightLogicProps,
}: {
    insightLogicProps: InsightLogicProps
}): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]) {
        return null
    }

    return <InsightSceneMenuBarInner insightLogicProps={insightLogicProps} />
}

function InsightSceneMenuBarInner({ insightLogicProps }: { insightLogicProps: InsightLogicProps }): JSX.Element {
    const theInsightLogic = insightLogic(insightLogicProps)
    const { insightProps, insight, hasDashboardItemId, canEditInsight, isSavingTags } = useValues(theInsightLogic)
    const { duplicateInsight, deleteInsight, setInsightMetadata } = useActions(theInsightLogic)

    const theInsightDataLogic = insightDataLogic(insightProps)
    const { query, hogQL, exportContext, hogQLVariables, canEditInSqlEditor, showQueryEditor, showDebugPanel } =
        useValues(theInsightDataLogic)
    const { toggleQueryEditorPanel, toggleDebugPanel } = useActions(theInsightDataLogic)

    const { insightMode, dashboardId } = useValues(insightSceneLogic)
    const { setInsightMode } = useActions(insightSceneLogic)

    const { createStaticCohort, startExport } = useActions(exportsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { openCreateFromInsightModal } = useActions(endpointLogic)
    const { push } = useActions(router)
    const { openTerraformModal, openAddToDashboardModal } = useActions(insightModalsLogic(insightLogicProps))

    const { canCopyToProject } = useValues(interProjectCopyLogic)
    const { tags: allExistingTags } = useValues(tagsModel)

    const { user, hasAvailableFeature } = useValues(userLogic)
    const { preflight } = useValues(preflightLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { instanceId: metalyticsInstanceId } = useValues(metalyticsLogic)

    // Creating an export requires editor access to the export resource.
    const exportAccessControlDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Export,
        AccessControlLevel.Editor
    )
    const sharingDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.SharingConfiguration,
        AccessControlLevel.Viewer
    )

    const isSavedInsight = hasDashboardItemId && !!insight?.id && !!insight?.short_id
    const canExport = exportContext != null && insight.short_id != null
    const showCohort =
        hogQL != null &&
        (isDataTableNode(query) || isDataVisualizationNode(query) || isHogQLQuery(query) || isEventsQuery(query))
    const canShowDebugPanel = isSavedInsight && (user?.is_staff || user?.is_impersonated || !preflight?.cloud)
    const showMetalytics =
        isSavedInsight &&
        metalyticsInstanceId != null &&
        featureFlags['metalytics'] &&
        hasAvailableFeature(AvailableFeature.AUDIT_LOGS)

    const handleToggleQueryEditorPanel = (): void => {
        if (hasDashboardItemId && insightMode !== ItemMode.Edit) {
            setInsightMode(ItemMode.Edit, null)
            if (showQueryEditor) {
                return
            }
        }
        toggleQueryEditorPanel()
    }

    // Per-menu visibility — empty menus' triggers are not rendered.
    const showCopyToProject = isSavedInsight && canCopyToProject
    const showFileMenu = true // file ops (project tree, terraform) always available
    const showEditMenu = true // duplicate always available
    const showCreateEndpoint =
        featureFlags[FEATURE_FLAGS.ENDPOINTS] &&
        isSavedInsight &&
        !getAccessControlDisabledReason(AccessControlResourceType.Endpoint, AccessControlLevel.Editor)
    const showAddToNotebook = isSavedInsight
    const showCreateMenu =
        showCreateEndpoint ||
        showCohort ||
        isSavedInsight /* add-to-dashboard, add-to-notebook, subscribe, alerts, share */
    const showMetadataMenu = true // tags + activity always shown
    const showStateMenu = isSavedInsight // favorite + view-source toggle
    const showStaffMenu = canShowDebugPanel

    return (
        <SceneMenuBar>
            {showFileMenu && (
                <SceneMenuBarMenu label="File" dataAttr={`${RESOURCE_TYPE}-menubar-file`}>
                    {showCreateMenu && (
                        <>
                            <SceneMenuBarSubMenu label="Create">
                                {isSavedInsight && (
                                    <SceneMenuBarItem
                                        opensFloatingUi
                                        onClick={openAddToDashboardModal}
                                        data-attr={`${RESOURCE_TYPE}-menubar-add-to-dashboard`}
                                    >
                                        <IconPlusSmall />
                                        Add to dashboard
                                    </SceneMenuBarItem>
                                )}
                                {showAddToNotebook && (
                                    <SceneMenuBarAddToNotebook
                                        dataAttrKey={RESOURCE_TYPE}
                                        notebookSelectButtonProps={{
                                            resource: {
                                                type: NotebookNodeType.Query,
                                                attrs: {
                                                    query: {
                                                        kind: NodeKind.SavedInsightNode,
                                                        shortId: insight.short_id,
                                                    },
                                                },
                                            },
                                        }}
                                    />
                                )}
                                {showCreateEndpoint && (
                                    <SceneMenuBarItem
                                        opensFloatingUi
                                        onClick={openCreateFromInsightModal}
                                        data-attr={`${RESOURCE_TYPE}-menubar-create-endpoint`}
                                    >
                                        <IconEndpoints />
                                        Endpoint
                                    </SceneMenuBarItem>
                                )}
                                {showCohort && (
                                    <SceneMenuBarItem
                                        opensFloatingUi
                                        onClick={() =>
                                            openSaveAsCohortDialog(createStaticCohort, hogQL!, hogQLVariables)
                                        }
                                        data-attr={`${RESOURCE_TYPE}-menubar-create-cohort`}
                                    >
                                        <IconPeople />
                                        Static cohort
                                    </SceneMenuBarItem>
                                )}
                                {isSavedInsight && (
                                    <SceneMenuBarItem
                                        onClick={() => push(urlForSubscriptions({ insightShortId: insight.short_id }))}
                                        data-attr={`${RESOURCE_TYPE}-menubar-subscribe`}
                                    >
                                        <IconBell />
                                        Subscription
                                    </SceneMenuBarItem>
                                )}
                                {isSavedInsight && (
                                    <SceneMenuBarItem
                                        onClick={() => push(urls.insightAlerts(insight.short_id!))}
                                        data-attr={`${RESOURCE_TYPE}-menubar-alerts`}
                                    >
                                        <IconWarning />
                                        Alert
                                    </SceneMenuBarItem>
                                )}
                                {isSavedInsight && (
                                    <SceneMenuBarItem
                                        onClick={() => push(urls.insightSharing(insight.short_id!))}
                                        data-attr={`${RESOURCE_TYPE}-menubar-share`}
                                        disabled={!!sharingDisabledReason}
                                        tooltip={sharingDisabledReason ?? undefined}
                                    >
                                        <IconShare />
                                        Share or embed
                                    </SceneMenuBarItem>
                                )}
                            </SceneMenuBarSubMenu>
                            <SceneMenuBarSeparator />
                        </>
                    )}
                    <SceneMenuBarFileItems dataAttrKey={RESOURCE_TYPE} />
                    {showCopyToProject && (
                        <SceneMenuBarItem
                            onClick={() => push(urls.resourceTransfer('Insight', insight.id!))}
                            data-attr={`${RESOURCE_TYPE}-menubar-copy-to-project`}
                        >
                            <IconCopy />
                            Copy to another project
                        </SceneMenuBarItem>
                    )}
                    <SceneMenuBarItem
                        opensFloatingUi
                        onClick={openTerraformModal}
                        data-attr={`${RESOURCE_TYPE}-menubar-terraform`}
                    >
                        <IconCode2 />
                        Manage with Terraform
                    </SceneMenuBarItem>
                    {canExport && (
                        <SceneMenuBarSubMenu label="Export">
                            <SceneMenuBarItem
                                disabled={!!exportAccessControlDisabledReason}
                                tooltip={exportAccessControlDisabledReason ?? undefined}
                                onClick={() =>
                                    startExport({
                                        export_format: ExporterFormat.PNG,
                                        insight: insight.id,
                                        export_context: exportContext,
                                    })
                                }
                                data-attr={`${RESOURCE_TYPE}-menubar-export-png`}
                            >
                                <IconDownload />
                                PNG
                            </SceneMenuBarItem>
                            <SceneMenuBarItem
                                disabled={!!exportAccessControlDisabledReason}
                                tooltip={exportAccessControlDisabledReason ?? undefined}
                                onClick={() =>
                                    startExport({
                                        export_format: ExporterFormat.CSV,
                                        export_context: exportContext,
                                    })
                                }
                                data-attr={`${RESOURCE_TYPE}-menubar-export-csv`}
                            >
                                <IconDownload />
                                CSV
                            </SceneMenuBarItem>
                            <SceneMenuBarItem
                                disabled={!!exportAccessControlDisabledReason}
                                tooltip={exportAccessControlDisabledReason ?? undefined}
                                onClick={() =>
                                    startExport({
                                        export_format: ExporterFormat.XLSX,
                                        export_context: exportContext,
                                    })
                                }
                                data-attr={`${RESOURCE_TYPE}-menubar-export-xlsx`}
                            >
                                <IconDownload />
                                XLSX
                            </SceneMenuBarItem>
                        </SceneMenuBarSubMenu>
                    )}
                    {isSavedInsight && (
                        <>
                            <SceneMenuBarSeparator />
                            <AccessControlAction
                                resourceType={AccessControlResourceType.Insight}
                                minAccessLevel={AccessControlLevel.Editor}
                            >
                                {({ disabledReason }) => (
                                    <SceneMenuBarItem
                                        variant="destructive"
                                        disabled={!!disabledReason}
                                        onClick={() => deleteInsight(dashboardId ?? null)}
                                        data-attr={`${RESOURCE_TYPE}-menubar-delete`}
                                    >
                                        <IconTrash />
                                        Delete insight
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
                        onClick={() => duplicateInsight(insight as QueryBasedInsightModel, true)}
                        data-attr={`${RESOURCE_TYPE}-menubar-duplicate`}
                    >
                        <IconCopy />
                        Duplicate
                    </SceneMenuBarItem>
                    {canEditInSqlEditor && (
                        <SceneMenuBarItem
                            onClick={() => push(urls.sqlEditor({ query: hogQL ?? undefined }))}
                            data-attr={`${RESOURCE_TYPE}-menubar-edit-sql`}
                        >
                            <IconPencil />
                            Edit in SQL editor
                        </SceneMenuBarItem>
                    )}
                    {showStateMenu && (
                        <>
                            <SceneMenuBarSeparator />
                            <SceneMenuBarCheckboxItem
                                checked={!!insight.favorited}
                                onCheckedChange={(checked) => setInsightMetadata({ favorited: checked })}
                                data-attr={`${RESOURCE_TYPE}-menubar-favorite`}
                            >
                                Favorite
                            </SceneMenuBarCheckboxItem>
                            <SceneMenuBarCheckboxItem
                                checked={showQueryEditor}
                                onCheckedChange={handleToggleQueryEditorPanel}
                                data-attr={`${RESOURCE_TYPE}-menubar-view-source`}
                            >
                                View source
                            </SceneMenuBarCheckboxItem>
                        </>
                    )}
                </SceneMenuBarMenu>
            )}
            {showMetadataMenu && (
                <SceneMenuBarPopover
                    label="Metadata"
                    dataAttr={`${RESOURCE_TYPE}-menubar-metadata`}
                    contentClassName="w-80 p-2 flex flex-col gap-2"
                >
                    <SceneTagsCombobox
                        onSave={(tags) => setInsightMetadata({ tags })}
                        tags={insight.tags}
                        tagsAvailable={allExistingTags}
                        dataAttrKey={RESOURCE_TYPE}
                        canEdit={canEditInsight}
                        loading={isSavingTags}
                    />
                    <SceneActivityIndicator
                        at={insight.last_modified_at}
                        by={insight.last_modified_by}
                        prefix="Last modified"
                    />
                    {showMetalytics && (
                        <Button
                            type="button"
                            variant="ghost"
                            size="sm"
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
            {showStaffMenu && (
                <SceneMenuBarMenu label="Staff only" dataAttr={`${RESOURCE_TYPE}-menubar-staff`}>
                    <SceneMenuBarCheckboxItem
                        checked={showDebugPanel}
                        onCheckedChange={toggleDebugPanel}
                        data-attr={`${RESOURCE_TYPE}-menubar-debug-panel`}
                    >
                        Show debug panel
                    </SceneMenuBarCheckboxItem>
                </SceneMenuBarMenu>
            )}
        </SceneMenuBar>
    )
}
