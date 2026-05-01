import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconCode2, IconCopy, IconGraph, IconNotebook, IconPalette, IconTrash } from '@posthog/icons'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { SceneExportDropdownMenu } from 'lib/components/Scenes/InsightOrDashboard/SceneExportDropdownMenu'
import { SceneDuplicate } from 'lib/components/Scenes/SceneDuplicate'
import { SceneFile } from 'lib/components/Scenes/SceneFile'
import { SceneFullscreen } from 'lib/components/Scenes/SceneFullscreen'
import { SceneMetalyticsSummaryButton } from 'lib/components/Scenes/SceneMetalyticsSummaryButton'
import { ScenePin } from 'lib/components/Scenes/ScenePin'
import { SceneSubscribeButton } from 'lib/components/Scenes/SceneSubscribeButton'
import { SceneTags } from 'lib/components/Scenes/SceneTags'
import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { slugify } from 'lib/utils'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { deleteDashboardLogic } from 'scenes/dashboard/deleteDashboardLogic'
import { duplicateDashboardLogic } from 'scenes/dashboard/duplicateDashboardLogic'
import { interProjectCopyLogic } from 'scenes/resource-transfer/interProjectCopyLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import {
    ScenePanel,
    ScenePanelActionsSection,
    ScenePanelDivider,
    ScenePanelInfoSection,
} from '~/layout/scenes/SceneLayout'
import { sceneLayoutLogic } from '~/layout/scenes/sceneLayoutLogic'
import { notebooksModel } from '~/models/notebooksModel'
import { tagsModel } from '~/models/tagsModel'
import { AccessControlLevel, AccessControlResourceType, DashboardMode, ExporterFormat } from '~/types'

import { dashboardInsightColorsModalLogic } from './dashboardInsightColorsModalLogic'
import { dashboardLogic } from './dashboardLogic'
import { DashboardTemplateModal } from './dashboards/templates/DashboardTemplateModal'
import { DashboardSaveAsTemplateSceneActions } from './DashboardSaveAsTemplateSceneActions'

const RESOURCE_TYPE = 'dashboard'

export function DashboardScenePanel(): JSX.Element | null {
    const {
        dashboard,
        dashboardMode,
        canEditDashboard,
        isSavingTags,
        isPinned,
        asDashboardTemplate,
        effectiveEditBarFilters,
        effectiveDashboardVariableOverrides,
        tiles,
        apiUrl,
    } = useValues(dashboardLogic)
    const { setDashboardMode, updateDashboardTags, togglePinned, setTerraformModalOpen } = useActions(dashboardLogic)
    const { createNotebookFromDashboard } = useActions(notebooksModel)
    const { showInsightColorsModal } = useActions(dashboardInsightColorsModalLogic)
    const { newTab } = useActions(sceneLogic)
    const { setScenePanelOpen } = useActions(sceneLayoutLogic)
    const { showDuplicateDashboardModal } = useActions(duplicateDashboardLogic)
    const { showDeleteDashboardModal } = useActions(deleteDashboardLogic)

    const { user } = useValues(userLogic)
    const { tags } = useValues(tagsModel)
    const { canCopyToProject } = useValues(interProjectCopyLogic)
    const hasDashboardColors = useFeatureFlag('PRODUCT_ANALYTICS_DASHBOARD_COLORS')

    const { push } = useActions(router)

    return (
        <ScenePanel>
            <ScenePanelInfoSection>
                <SceneTags
                    onSave={(tags) => updateDashboardTags(tags)}
                    canEdit={canEditDashboard}
                    tags={dashboard?.tags}
                    tagsAvailable={tags.filter((tag) => !dashboard?.tags?.includes(tag))}
                    dataAttrKey={RESOURCE_TYPE}
                    loading={isSavingTags}
                />
                <SceneFile dataAttrKey={RESOURCE_TYPE} />
                <SceneActivityIndicator at={dashboard?.created_at} by={dashboard?.created_by} prefix="Created" />
            </ScenePanelInfoSection>
            <ScenePanelDivider />

            <ScenePanelActionsSection>
                {dashboard && (
                    <>
                        <SceneDuplicate
                            dataAttrKey={RESOURCE_TYPE}
                            onClick={() => showDuplicateDashboardModal(dashboard.id, dashboard.name)}
                        />
                        {canCopyToProject && (
                            <ButtonPrimitive
                                menuItem
                                onClick={() => push(urls.resourceTransfer('Dashboard', dashboard.id))}
                                data-attr="dashboard-copy-to-project"
                                tooltip="Copy this dashboard to another project"
                            >
                                <IconCopy />
                                Copy to another project
                            </ButtonPrimitive>
                        )}
                        <ScenePin dataAttrKey={RESOURCE_TYPE} onClick={togglePinned} isPinned={isPinned} />
                        <SceneFullscreen
                            dataAttrKey={RESOURCE_TYPE}
                            onClick={() => {
                                if (dashboardMode === DashboardMode.Fullscreen) {
                                    setDashboardMode(null, DashboardEventSource.SceneCommonButtons)
                                } else {
                                    setDashboardMode(DashboardMode.Fullscreen, DashboardEventSource.SceneCommonButtons)
                                }
                            }}
                            isFullscreen={dashboardMode === DashboardMode.Fullscreen}
                        />
                    </>
                )}

                {dashboard && canEditDashboard && (
                    <>
                        {hasDashboardColors && (
                            <ButtonPrimitive
                                onClick={() => showInsightColorsModal(dashboard.id)}
                                menuItem
                                data-attr={`${RESOURCE_TYPE}-customize-colors`}
                            >
                                <IconPalette />
                                Customize colors
                            </ButtonPrimitive>
                        )}
                        <ButtonPrimitive
                            onClick={() => createNotebookFromDashboard(dashboard)}
                            menuItem
                            data-attr={`${RESOURCE_TYPE}-create-notebook-from-dashboard`}
                        >
                            <IconNotebook />
                            Create notebook from dashboard
                        </ButtonPrimitive>
                        <SceneSubscribeButton dashboardId={dashboard.id} dataAttrKey={RESOURCE_TYPE} />
                        <SceneExportDropdownMenu
                            dropdownMenuItems={[
                                {
                                    format: ExporterFormat.PNG,
                                    dashboard: dashboard.id,
                                    context: {
                                        path: apiUrl(),
                                        variables_override: effectiveDashboardVariableOverrides,
                                    },
                                    dataAttr: `${RESOURCE_TYPE}-export-png`,
                                },
                                ...(user?.is_staff
                                    ? [
                                          {
                                              format: ExporterFormat.JSON,
                                              context: {
                                                  localData: JSON.stringify(asDashboardTemplate),
                                                  filename: `dashboard-${slugify(dashboard?.name || 'nameless dashboard')}.json`,
                                                  mediaType: ExporterFormat.JSON,
                                              },
                                              dataAttr: `${RESOURCE_TYPE}-export-json`,
                                          },
                                      ]
                                    : []),
                            ]}
                        />
                    </>
                )}

                {dashboard && (
                    <ButtonPrimitive
                        onClick={() => setTerraformModalOpen(true)}
                        menuItem
                        data-attr={`${RESOURCE_TYPE}-manage-terraform`}
                    >
                        <IconCode2 />
                        Manage with Terraform
                    </ButtonPrimitive>
                )}

                <DashboardSaveAsTemplateSceneActions />

                {dashboard && <SceneMetalyticsSummaryButton dataAttrKey={RESOURCE_TYPE} />}
                {dashboard && (
                    <ButtonPrimitive
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
                                newTab(url)
                            })
                            setScenePanelOpen(false)
                        }}
                        menuItem
                        data-attr="open-insights-in-new-posthog-tabs"
                        disabledReasons={{
                            'Cannot open insights when editing dashboard': dashboardMode === DashboardMode.Edit,
                            'Dashboard has no insights': tiles.length === 0,
                        }}
                    >
                        <IconGraph />
                        Open insights in new PostHog tabs
                    </ButtonPrimitive>
                )}
            </ScenePanelActionsSection>
            {dashboard && canEditDashboard && (
                <>
                    <ScenePanelDivider />
                    <ScenePanelActionsSection>
                        <AccessControlAction
                            resourceType={AccessControlResourceType.Dashboard}
                            minAccessLevel={AccessControlLevel.Editor}
                            userAccessLevel={dashboard.user_access_level}
                        >
                            {({ disabledReason }) => (
                                <ButtonPrimitive
                                    menuItem
                                    variant="danger"
                                    disabled={!!disabledReason}
                                    {...(disabledReason && { tooltip: disabledReason })}
                                    onClick={() => showDeleteDashboardModal(dashboard.id)}
                                >
                                    <IconTrash />
                                    Delete dashboard
                                </ButtonPrimitive>
                            )}
                        </AccessControlAction>
                    </ScenePanelActionsSection>
                </>
            )}
            <DashboardTemplateModal />
        </ScenePanel>
    )
}
