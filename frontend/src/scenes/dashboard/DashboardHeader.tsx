import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useMemo, useState } from 'react'

import {
    IconCode2,
    IconGraph,
    IconGridMasonry,
    IconNotebook,
    IconPalette,
    IconPlusSmall,
    IconScreen,
    IconShare,
    IconTrash,
} from '@posthog/icons'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { TextCardModal } from 'lib/components/Cards/TextCard/TextCardModal'
import { ExportButtonItem } from 'lib/components/ExportButton/ExportButton'
import { FullScreen } from 'lib/components/FullScreen'
import { SceneExportDropdownMenu } from 'lib/components/Scenes/InsightOrDashboard/SceneExportDropdownMenu'
import { SceneDuplicate } from 'lib/components/Scenes/SceneDuplicate'
import { SceneFile } from 'lib/components/Scenes/SceneFile'
import { SceneFullscreen } from 'lib/components/Scenes/SceneFullscreen'
import { SceneMetalyticsSummaryButton } from 'lib/components/Scenes/SceneMetalyticsSummaryButton'
import { ScenePin } from 'lib/components/Scenes/ScenePin'
import { SceneSubscribeButton } from 'lib/components/Scenes/SceneSubscribeButton'
import { SceneTags } from 'lib/components/Scenes/SceneTags'
import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'
import { SharingModal } from 'lib/components/Sharing/SharingModal'
import { SubscriptionsModal } from 'lib/components/Subscriptions/SubscriptionsModal'
import { TerraformExportModal } from 'lib/components/TerraformExporter/TerraformExportModal'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { slugify } from 'lib/utils'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { DeleteDashboardModal } from 'scenes/dashboard/DeleteDashboardModal'
import { DuplicateDashboardModal } from 'scenes/dashboard/DuplicateDashboardModal'
import { deleteDashboardLogic } from 'scenes/dashboard/deleteDashboardLogic'
import { duplicateDashboardLogic } from 'scenes/dashboard/duplicateDashboardLogic'
import { MaxTool } from 'scenes/max/MaxTool'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import {
    ScenePanel,
    ScenePanelActionsSection,
    ScenePanelDivider,
    ScenePanelInfoSection,
} from '~/layout/scenes/SceneLayout'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { sceneLayoutLogic } from '~/layout/scenes/sceneLayoutLogic'
import { dashboardsModel } from '~/models/dashboardsModel'
import { notebooksModel } from '~/models/notebooksModel'
import { tagsModel } from '~/models/tagsModel'
import { AccessControlLevel, AccessControlResourceType, DashboardMode, ExporterFormat } from '~/types'

import { DashboardInsightColorsModal } from './DashboardInsightColorsModal'
import { DashboardTemplateEditor } from './DashboardTemplateEditor'
import { addInsightToDashboardLogic } from './addInsightToDashboardModalLogic'
import { dashboardInsightColorsModalLogic } from './dashboardInsightColorsModalLogic'
import { DashboardLoadAction, dashboardLogic } from './dashboardLogic'
import { dashboardTemplateEditorLogic } from './dashboardTemplateEditorLogic'

const RESOURCE_TYPE = 'dashboard'

export const DASHBOARD_CANNOT_EDIT_MESSAGE =
    "You don't have edit permissions for this dashboard. Ask a dashboard collaborator with edit access to add you."

export function DashboardHeader(): JSX.Element | null {
    const {
        dashboard,
        dashboardLoading,
        dashboardMode,
        canEditDashboard,
        showSubscriptions,
        subscriptionId,
        apiUrl,
        showTextTileModal,
        textTileId,
    } = useValues(dashboardLogic)
    const { setDashboardMode, triggerDashboardUpdate, loadDashboard } = useActions(dashboardLogic)
    const { asDashboardTemplate, effectiveEditBarFilters, effectiveDashboardVariableOverrides, tiles } =
        useValues(dashboardLogic)
    const { updateDashboard, pinDashboard, unpinDashboard } = useActions(dashboardsModel)
    const { createNotebookFromDashboard } = useActions(notebooksModel)
    const { showAddInsightToDashboardModal } = useActions(addInsightToDashboardLogic)

    const { setDashboardTemplate, openDashboardTemplateEditor } = useActions(dashboardTemplateEditorLogic)
    const { showInsightColorsModal } = useActions(dashboardInsightColorsModalLogic)
    const { newTab } = useActions(sceneLogic)
    const { setScenePanelOpen } = useActions(sceneLayoutLogic)

    const { user } = useValues(userLogic)

    const { showDuplicateDashboardModal } = useActions(duplicateDashboardLogic)
    const { showDeleteDashboardModal } = useActions(deleteDashboardLogic)

    const { tags } = useValues(tagsModel)

    const { push } = useActions(router)

    const [isPinned, setIsPinned] = useState(dashboard?.pinned)

    const [terraformModalOpen, setTerraformModalOpen] = useState(false)
    const terraformFeatureEnabled = useFeatureFlag('MANAGE_INSIGHTS_THROUGH_TERRAFORM')

    const isNewDashboard = useMemo(() => {
        if (!dashboard || dashboardLoading) {
            return false
        }

        // A dashboard is considered new if:
        // 1. It's a fresh duplicate (has _highlight set), OR
        // 2. It's a blank dashboard with default name, OR
        // 3. It was created recently (within last 30 seconds) - catches templates, OR
        // 4. It has no tiles yet (completely empty)
        const now = new Date()
        const createdAt = new Date(dashboard.created_at)
        const isRecentlyCreated = now.getTime() - createdAt.getTime() < 30000 // 30 seconds

        return (
            Boolean(dashboard._highlight) ||
            dashboard.name === 'New Dashboard' ||
            isRecentlyCreated ||
            !dashboard.tiles ||
            dashboard.tiles.length === 0
        )
    }, [dashboard, dashboardLoading])

    const hasDashboardColors = useFeatureFlag('PRODUCT_ANALYTICS_DASHBOARD_COLORS')

    const exportOptions: ExportButtonItem[] = [
        {
            export_format: ExporterFormat.PNG,
            dashboard: dashboard?.id,
            export_context: {
                path: apiUrl(),
            },
        },
    ]
    if (user?.is_staff) {
        exportOptions.push({
            export_format: ExporterFormat.JSON,
            export_context: {
                localData: JSON.stringify(asDashboardTemplate),
                filename: `dashboard-${slugify(dashboard?.name || 'nameless dashboard')}.json`,
                mediaType: ExporterFormat.JSON,
            },
        })
    }
    useEffect(() => {
        setIsPinned(dashboard?.pinned)
    }, [dashboard?.pinned])

    const hasUpsertDashboardFeatureFlag = useFeatureFlag('POSTHOG_AI_UPSERT_DASHBOARD')

    return dashboard || dashboardLoading ? (
        <>
            {dashboardMode === DashboardMode.Fullscreen && (
                <FullScreen onExit={() => setDashboardMode(null, DashboardEventSource.Browser)} />
            )}
            {dashboard && (
                <>
                    <SubscriptionsModal
                        isOpen={showSubscriptions}
                        closeModal={() => push(urls.dashboard(dashboard.id))}
                        dashboardId={dashboard.id}
                        subscriptionId={subscriptionId}
                    />
                    <SharingModal
                        title="Dashboard permissions & sharing"
                        isOpen={dashboardMode === DashboardMode.Sharing}
                        closeModal={() => push(urls.dashboard(dashboard.id))}
                        dashboardId={dashboard.id}
                        userAccessLevel={dashboard.user_access_level}
                    />
                    {canEditDashboard && (
                        <TextCardModal
                            isOpen={showTextTileModal}
                            onClose={() => push(urls.dashboard(dashboard.id))}
                            dashboard={dashboard}
                            textTileId={textTileId}
                        />
                    )}
                    {canEditDashboard && <DeleteDashboardModal />}
                    {canEditDashboard && <DuplicateDashboardModal />}
                    {canEditDashboard && <DashboardInsightColorsModal />}
                    {user?.is_staff && <DashboardTemplateEditor />}
                    {terraformFeatureEnabled && (
                        <TerraformExportModal
                            isOpen={terraformModalOpen}
                            onClose={() => setTerraformModalOpen(false)}
                            resource={{ type: 'dashboard', data: dashboard }}
                        />
                    )}
                </>
            )}

            <ScenePanel>
                <ScenePanelInfoSection>
                    <SceneTags
                        onSave={(tags) => {
                            triggerDashboardUpdate({ tags })
                        }}
                        canEdit={canEditDashboard}
                        tags={dashboard?.tags}
                        tagsAvailable={tags.filter((tag) => !dashboard?.tags?.includes(tag))}
                        dataAttrKey={RESOURCE_TYPE}
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
                            <ScenePin
                                dataAttrKey={RESOURCE_TYPE}
                                onClick={() => {
                                    if (isPinned) {
                                        unpinDashboard(dashboard.id, DashboardEventSource.SceneCommonButtons)
                                        setIsPinned(false)
                                    } else {
                                        pinDashboard(dashboard.id, DashboardEventSource.SceneCommonButtons)
                                        setIsPinned(true)
                                    }
                                }}
                                isPinned={isPinned ?? false}
                            />
                            <SceneFullscreen
                                dataAttrKey={RESOURCE_TYPE}
                                onClick={() => {
                                    if (dashboardMode === DashboardMode.Fullscreen) {
                                        setDashboardMode(null, DashboardEventSource.SceneCommonButtons)
                                    } else {
                                        setDashboardMode(
                                            DashboardMode.Fullscreen,
                                            DashboardEventSource.SceneCommonButtons
                                        )
                                    }
                                }}
                                isFullscreen={dashboardMode === DashboardMode.Fullscreen}
                            />
                        </>
                    )}

                    {dashboard && canEditDashboard && hasDashboardColors && (
                        <ButtonPrimitive
                            onClick={() => showInsightColorsModal(dashboard.id)}
                            menuItem
                            data-attr={`${RESOURCE_TYPE}-customize-colors`}
                        >
                            <IconPalette />
                            Customize colors
                        </ButtonPrimitive>
                    )}
                    {dashboard && canEditDashboard && (
                        <AppShortcut
                            name="ToggleEditMode"
                            scope={Scene.Dashboard}
                            keybind={[keyBinds.edit]}
                            intent="Toggle edit mode"
                            interaction="click"
                        >
                            <ButtonPrimitive
                                onClick={() => {
                                    if (dashboardMode === DashboardMode.Edit) {
                                        setDashboardMode(null, DashboardEventSource.SceneCommonButtons)
                                    } else {
                                        setDashboardMode(DashboardMode.Edit, DashboardEventSource.SceneCommonButtons)
                                    }
                                }}
                                menuItem
                                active={dashboardMode === DashboardMode.Edit}
                                data-attr={`${RESOURCE_TYPE}-edit-layout`}
                                tooltip="Toggle edit mode"
                                tooltipPlacement="left"
                            >
                                <IconGridMasonry />
                                Edit layout
                            </ButtonPrimitive>
                        </AppShortcut>
                    )}

                    {dashboard && canEditDashboard && (
                        <ButtonPrimitive
                            onClick={() => createNotebookFromDashboard(dashboard)}
                            menuItem
                            data-attr={`${RESOURCE_TYPE}-create-notebook-from-dashboard`}
                        >
                            <IconNotebook />
                            Create notebook from dashboard
                        </ButtonPrimitive>
                    )}

                    {dashboard && canEditDashboard && (
                        <SceneSubscribeButton dashboardId={dashboard.id} dataAttrKey={RESOURCE_TYPE} />
                    )}

                    {dashboard && canEditDashboard && (
                        <SceneExportDropdownMenu
                            dropdownMenuItems={[
                                {
                                    format: ExporterFormat.PNG,
                                    dashboard: dashboard.id,
                                    context: {
                                        path: apiUrl(),
                                    },
                                    dataAttr: `${RESOURCE_TYPE}-export-png`,
                                },
                                ...(user?.is_staff
                                    ? [
                                          {
                                              format: ExporterFormat.JSON,
                                              context: {
                                                  localData: JSON.stringify(asDashboardTemplate),
                                                  filename: `dashboard-${slugify(
                                                      dashboard?.name || 'nameless dashboard'
                                                  )}.json`,
                                                  mediaType: ExporterFormat.JSON,
                                              },
                                              dataAttr: `${RESOURCE_TYPE}-export-json`,
                                          },
                                      ]
                                    : []),
                            ]}
                        />
                    )}

                    {dashboard && terraformFeatureEnabled && (
                        <ButtonPrimitive
                            onClick={() => setTerraformModalOpen(true)}
                            menuItem
                            data-attr={`${RESOURCE_TYPE}-manage-terraform`}
                        >
                            <IconCode2 />
                            Manage with Terraform
                        </ButtonPrimitive>
                    )}

                    {user?.is_staff && (
                        <ButtonPrimitive
                            onClick={() => {
                                if (asDashboardTemplate) {
                                    setDashboardTemplate(asDashboardTemplate)
                                    openDashboardTemplateEditor()
                                }
                            }}
                            menuItem
                        >
                            <IconScreen />
                            Save as template
                        </ButtonPrimitive>
                    )}

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
            </ScenePanel>

            <SceneTitleSection
                name={dashboard?.name}
                description={dashboard?.description}
                resourceType={{
                    type: sceneConfigurations[Scene.Dashboard].iconType || 'default_icon_type',
                }}
                onNameChange={(value) => updateDashboard({ id: dashboard?.id, name: value, allowUndo: true })}
                onDescriptionChange={(value) =>
                    updateDashboard({ id: dashboard?.id, description: value, allowUndo: true })
                }
                markdown
                canEdit={canEditDashboard}
                isLoading={dashboardLoading}
                forceEdit={dashboardMode === DashboardMode.Edit || isNewDashboard}
                renameDebounceMs={1000}
                actions={
                    <>
                        {dashboardMode === DashboardMode.Edit ? (
                            <>
                                <LemonButton
                                    data-attr="dashboard-edit-mode-discard"
                                    type="secondary"
                                    onClick={() =>
                                        setDashboardMode(null, DashboardEventSource.DashboardHeaderDiscardChanges)
                                    }
                                    size="small"
                                    tabIndex={9}
                                >
                                    Cancel
                                </LemonButton>
                                <AppShortcut
                                    name="SaveDashboard"
                                    keybind={[keyBinds.save]}
                                    intent="Save dashboard"
                                    interaction="click"
                                    scope={Scene.Dashboard}
                                >
                                    <LemonButton
                                        data-attr="dashboard-edit-mode-save"
                                        type="primary"
                                        onClick={() =>
                                            setDashboardMode(null, DashboardEventSource.DashboardHeaderSaveDashboard)
                                        }
                                        size="small"
                                        tabIndex={10}
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
                        ) : dashboardMode === DashboardMode.Fullscreen ? (
                            <LemonButton
                                type="secondary"
                                onClick={() =>
                                    setDashboardMode(null, DashboardEventSource.DashboardHeaderExitFullscreen)
                                }
                                data-attr="dashboard-exit-presentation-mode"
                                disabled={dashboardLoading}
                                size="small"
                            >
                                Exit full screen
                            </LemonButton>
                        ) : (
                            <>
                                {dashboard && (
                                    <>
                                        <LemonButton
                                            type="secondary"
                                            data-attr="dashboard-share-button"
                                            onClick={() => push(urls.dashboardSharing(dashboard.id))}
                                            size="small"
                                            icon={<IconShare fontSize="16" />}
                                            tooltip="Share"
                                            tooltipPlacement="top"
                                        />
                                    </>
                                )}
                                {dashboard ? (
                                    <>
                                        <AccessControlAction
                                            resourceType={AccessControlResourceType.Dashboard}
                                            minAccessLevel={AccessControlLevel.Editor}
                                            userAccessLevel={dashboard.user_access_level}
                                        >
                                            <AppShortcut
                                                name="AddTextTileToDashboard"
                                                scope={Scene.Dashboard}
                                                keybind={[keyBinds.dashboardAddTextTile]}
                                                intent="Add text card"
                                                interaction="click"
                                            >
                                                <LemonButton
                                                    onClick={() => {
                                                        push(urls.dashboardTextTile(dashboard.id, 'new'))
                                                    }}
                                                    data-attr="add-text-tile-to-dashboard"
                                                    type="secondary"
                                                    size="small"
                                                    tooltip="Add text card"
                                                    tooltipPlacement="top"
                                                    icon={<IconPlusSmall />}
                                                >
                                                    Text card
                                                </LemonButton>
                                            </AppShortcut>
                                        </AccessControlAction>
                                        <MaxTool
                                            identifier={
                                                hasUpsertDashboardFeatureFlag
                                                    ? 'upsert_dashboard'
                                                    : 'edit_current_dashboard'
                                            }
                                            context={{
                                                current_dashboard: dashboard
                                                    ? {
                                                          id: dashboard.id,
                                                          name: dashboard.name,
                                                          description: dashboard.description,
                                                          tags: dashboard.tags,
                                                      }
                                                    : undefined,
                                            }}
                                            contextDescription={
                                                dashboard
                                                    ? {
                                                          text: dashboard.name,
                                                          icon: iconForType('dashboard'),
                                                      }
                                                    : undefined
                                            }
                                            active={!!dashboard && canEditDashboard}
                                            callback={() => loadDashboard({ action: DashboardLoadAction.Update })}
                                            position="top-right"
                                        >
                                            <AccessControlAction
                                                resourceType={AccessControlResourceType.Dashboard}
                                                minAccessLevel={AccessControlLevel.Editor}
                                                userAccessLevel={dashboard.user_access_level}
                                            >
                                                <LemonButton
                                                    onClick={showAddInsightToDashboardModal}
                                                    type="primary"
                                                    data-attr="dashboard-add-graph-header"
                                                    size="small"
                                                >
                                                    <span className="pr-3">Add insight</span>
                                                </LemonButton>
                                            </AccessControlAction>
                                        </MaxTool>
                                    </>
                                ) : null}
                            </>
                        )}
                    </>
                }
            />
        </>
    ) : null
}
