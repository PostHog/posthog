import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useMemo, useState } from 'react'

import { IconGridMasonry, IconNotebook, IconPalette, IconScreen, IconTrash } from '@posthog/icons'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { TextCardModal } from 'lib/components/Cards/TextCard/TextCardModal'
import { ExportButtonItem } from 'lib/components/ExportButton/ExportButton'
import { FullScreen } from 'lib/components/FullScreen'
import { SceneExportDropdownMenu } from 'lib/components/Scenes/InsightOrDashboard/SceneExportDropdownMenu'
import { SceneCommonButtons } from 'lib/components/Scenes/SceneCommonButtons'
import { SceneFile } from 'lib/components/Scenes/SceneFile'
import { SceneMetalyticsSummaryButton } from 'lib/components/Scenes/SceneMetalyticsSummaryButton'
import { SceneSubscribeButton } from 'lib/components/Scenes/SceneSubscribeButton'
import { SceneTags } from 'lib/components/Scenes/SceneTags'
import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'
import { SharingModal } from 'lib/components/Sharing/SharingModal'
import { SubscriptionsModal } from 'lib/components/Subscriptions/SubscriptionsModal'
import { privilegeLevelToName } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { isLemonSelectSection } from 'lib/lemon-ui/LemonSelect'
import { ProfileBubbles } from 'lib/lemon-ui/ProfilePicture/ProfileBubbles'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { slugify } from 'lib/utils'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { DeleteDashboardModal } from 'scenes/dashboard/DeleteDashboardModal'
import { DuplicateDashboardModal } from 'scenes/dashboard/DuplicateDashboardModal'
import { deleteDashboardLogic } from 'scenes/dashboard/deleteDashboardLogic'
import { duplicateDashboardLogic } from 'scenes/dashboard/duplicateDashboardLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import {
    ScenePanel,
    ScenePanelActionsSection,
    ScenePanelCommonActions,
    ScenePanelDivider,
    ScenePanelInfoSection,
} from '~/layout/scenes/SceneLayout'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { dashboardsModel } from '~/models/dashboardsModel'
import { notebooksModel } from '~/models/notebooksModel'
import { tagsModel } from '~/models/tagsModel'
import {
    AccessControlLevel,
    AccessControlResourceType,
    DashboardMode,
    DashboardType,
    ExporterFormat,
    QueryBasedInsightModel,
} from '~/types'

import { DASHBOARD_RESTRICTION_OPTIONS } from './DashboardCollaborators'
import { DashboardInsightColorsModal } from './DashboardInsightColorsModal'
import { DashboardTemplateEditor } from './DashboardTemplateEditor'
import { addInsightToDashboardLogic } from './addInsightToDashboardModalLogic'
import { dashboardCollaboratorsLogic } from './dashboardCollaboratorsLogic'
import { dashboardInsightColorsModalLogic } from './dashboardInsightColorsModalLogic'
import { dashboardLogic } from './dashboardLogic'
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
    const { setDashboardMode, triggerDashboardUpdate } = useActions(dashboardLogic)
    const { asDashboardTemplate } = useValues(dashboardLogic)
    const { updateDashboard, pinDashboard, unpinDashboard } = useActions(dashboardsModel)
    const { createNotebookFromDashboard } = useActions(notebooksModel)
    const { showAddInsightToDashboardModal } = useActions(addInsightToDashboardLogic)
    const { setDashboardTemplate, openDashboardTemplateEditor } = useActions(dashboardTemplateEditorLogic)
    const { showInsightColorsModal } = useActions(dashboardInsightColorsModalLogic)

    const { user } = useValues(userLogic)

    const { showDuplicateDashboardModal } = useActions(duplicateDashboardLogic)
    const { showDeleteDashboardModal } = useActions(deleteDashboardLogic)

    const { tags } = useValues(tagsModel)

    const { push } = useActions(router)

    const [isPinned, setIsPinned] = useState(dashboard?.pinned)

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

    const hasDashboardColors = useFeatureFlag('DASHBOARD_COLORS')

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
                </>
            )}

            <ScenePanel>
                <ScenePanelCommonActions>
                    <SceneCommonButtons
                        dataAttrKey={RESOURCE_TYPE}
                        duplicate={
                            dashboard
                                ? { onClick: () => showDuplicateDashboardModal(dashboard.id, dashboard.name) }
                                : undefined
                        }
                        {...(canEditDashboard &&
                            dashboard && {
                                pinned: {
                                    onClick: () => {
                                        if (isPinned) {
                                            unpinDashboard(dashboard.id, DashboardEventSource.SceneCommonButtons)
                                            setIsPinned(false)
                                        } else {
                                            pinDashboard(dashboard.id, DashboardEventSource.SceneCommonButtons)
                                            setIsPinned(true)
                                        }
                                    },
                                    active: isPinned,
                                },
                            })}
                        fullscreen={
                            dashboard
                                ? {
                                      onClick: () => {
                                          if (dashboardMode === DashboardMode.Fullscreen) {
                                              setDashboardMode(null, DashboardEventSource.SceneCommonButtons)
                                          } else {
                                              setDashboardMode(
                                                  DashboardMode.Fullscreen,
                                                  DashboardEventSource.SceneCommonButtons
                                              )
                                          }
                                      },
                                      active: dashboardMode === DashboardMode.Fullscreen,
                                  }
                                : undefined
                        }
                    />
                </ScenePanelCommonActions>
                <ScenePanelDivider />
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
                    {dashboard && <SceneMetalyticsSummaryButton dataAttrKey={RESOURCE_TYPE} />}

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
                        <ButtonPrimitive
                            onClick={() =>
                                setDashboardMode(DashboardMode.Edit, DashboardEventSource.SceneCommonButtons)
                            }
                            menuItem
                            active={dashboardMode === DashboardMode.Edit}
                            data-attr={`${RESOURCE_TYPE}-edit-layout`}
                        >
                            <IconGridMasonry />
                            Edit layout <KeyboardShortcut e />
                        </ButtonPrimitive>
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
                    type: 'dashboard',
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
                                        {dashboard.access_control_version === 'v1' && (
                                            <CollaboratorBubbles
                                                dashboard={dashboard}
                                                onClick={() => push(urls.dashboardSharing(dashboard.id))}
                                            />
                                        )}
                                        <LemonButton
                                            type="secondary"
                                            data-attr="dashboard-share-button"
                                            onClick={() => push(urls.dashboardSharing(dashboard.id))}
                                            size="small"
                                        >
                                            Share
                                        </LemonButton>
                                    </>
                                )}
                                {dashboard ? (
                                    <AccessControlAction
                                        resourceType={AccessControlResourceType.Dashboard}
                                        minAccessLevel={AccessControlLevel.Editor}
                                        userAccessLevel={dashboard.user_access_level}
                                    >
                                        <LemonButton
                                            onClick={showAddInsightToDashboardModal}
                                            type="primary"
                                            data-attr="dashboard-add-graph-header"
                                            sideAction={{
                                                dropdown: {
                                                    placement: 'bottom-end',
                                                    overlay: (
                                                        <AccessControlAction
                                                            resourceType={AccessControlResourceType.Dashboard}
                                                            minAccessLevel={AccessControlLevel.Editor}
                                                            userAccessLevel={dashboard.user_access_level}
                                                        >
                                                            <LemonButton
                                                                fullWidth
                                                                onClick={() => {
                                                                    push(urls.dashboardTextTile(dashboard.id, 'new'))
                                                                }}
                                                                data-attr="add-text-tile-to-dashboard"
                                                            >
                                                                Add text card
                                                            </LemonButton>
                                                        </AccessControlAction>
                                                    ),
                                                },
                                                disabled: false,
                                                'data-attr': 'dashboard-add-dropdown',
                                            }}
                                            size="small"
                                        >
                                            Add insight
                                        </LemonButton>
                                    </AccessControlAction>
                                ) : null}
                            </>
                        )}
                    </>
                }
            />
            <SceneDivider />
        </>
    ) : null
}

function CollaboratorBubbles({
    dashboard,
    onClick,
}: {
    dashboard: DashboardType<QueryBasedInsightModel>
    onClick: () => void
}): JSX.Element | null {
    const { allCollaborators } = useValues(dashboardCollaboratorsLogic({ dashboardId: dashboard.id }))

    if (!dashboard) {
        return null
    }

    const effectiveRestrictionLevelOption = DASHBOARD_RESTRICTION_OPTIONS[dashboard.effective_restriction_level]
    const tooltipParts: string[] = []
    if (
        isLemonSelectSection(effectiveRestrictionLevelOption) &&
        typeof effectiveRestrictionLevelOption?.title === 'string'
    ) {
        tooltipParts.push(effectiveRestrictionLevelOption.title)
    }
    if (dashboard.is_shared) {
        tooltipParts.push('Shared publicly')
    }

    return (
        <ProfileBubbles
            people={allCollaborators.map((collaborator) => ({
                email: collaborator.user.email,
                name: collaborator.user.first_name,
                title: `${collaborator.user.first_name} <${collaborator.user.email}> (${
                    privilegeLevelToName[collaborator.level]
                })`,
            }))}
            tooltip={tooltipParts.join(' • ')}
            onClick={onClick}
        />
    )
}
