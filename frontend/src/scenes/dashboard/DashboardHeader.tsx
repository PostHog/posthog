import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useMemo, useState } from 'react'

import { IconGridMasonry, IconNotebook, IconPalette, IconScreen, IconTrash } from '@posthog/icons'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { AccessControlledLemonButton } from 'lib/components/AccessControlledLemonButton'
import { TextCardModal } from 'lib/components/Cards/TextCard/TextCardModal'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { ExportButton, ExportButtonItem } from 'lib/components/ExportButton/ExportButton'
import { FullScreen } from 'lib/components/FullScreen'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExportDropdownMenu } from 'lib/components/Scenes/InsightOrDashboard/SceneExportDropdownMenu'
import { SceneCommonButtons } from 'lib/components/Scenes/SceneCommonButtons'
import { SceneFile } from 'lib/components/Scenes/SceneFile'
import { SceneMetalyticsSummaryButton } from 'lib/components/Scenes/SceneMetalyticsSummaryButton'
import { SceneSubscribeButton } from 'lib/components/Scenes/SceneSubscribeButton'
import { SceneTags } from 'lib/components/Scenes/SceneTags'
import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'
import { SharingModal } from 'lib/components/Sharing/SharingModal'
import { SubscribeButton, SubscriptionsModal } from 'lib/components/Subscriptions/SubscriptionsModal'
import { FEATURE_FLAGS, privilegeLevelToName } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { isLemonSelectSection } from 'lib/lemon-ui/LemonSelect'
import { ProfileBubbles } from 'lib/lemon-ui/ProfilePicture/ProfileBubbles'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { humanFriendlyDetailedTime, slugify } from 'lib/utils'
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
    ScenePanelActions,
    ScenePanelCommonActions,
    ScenePanelDivider,
    ScenePanelMetaInfo,
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
    const { featureFlags } = useValues(featureFlagLogic)
    const newSceneLayout = featureFlags[FEATURE_FLAGS.NEW_SCENE_LAYOUT]

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

            <PageHeader
                buttons={
                    dashboardMode === DashboardMode.Edit ? (
                        <>
                            <LemonButton
                                data-attr="dashboard-edit-mode-discard"
                                type="secondary"
                                onClick={() =>
                                    setDashboardMode(null, DashboardEventSource.DashboardHeaderDiscardChanges)
                                }
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
                            onClick={() => setDashboardMode(null, DashboardEventSource.DashboardHeaderExitFullscreen)}
                            data-attr="dashboard-exit-presentation-mode"
                            disabled={dashboardLoading}
                        >
                            Exit full screen
                        </LemonButton>
                    ) : (
                        <>
                            {!newSceneLayout && (
                                <>
                                    <More
                                        data-attr="dashboard-three-dots-options-menu"
                                        overlay={
                                            dashboard ? (
                                                <>
                                                    {dashboard.created_by && (
                                                        <>
                                                            <div className="flex p-2 text-secondary">
                                                                Created by{' '}
                                                                {dashboard.created_by.first_name ||
                                                                    dashboard.created_by.email ||
                                                                    '-'}{' '}
                                                                on {humanFriendlyDetailedTime(dashboard.created_at)}
                                                            </div>
                                                            <LemonDivider />
                                                        </>
                                                    )}
                                                    {canEditDashboard && hasDashboardColors && (
                                                        <LemonButton
                                                            onClick={() => showInsightColorsModal(dashboard.id)}
                                                            fullWidth
                                                        >
                                                            Customize colors
                                                        </LemonButton>
                                                    )}

                                                    {canEditDashboard && (
                                                        <LemonButton
                                                            onClick={() =>
                                                                setDashboardMode(
                                                                    DashboardMode.Edit,
                                                                    DashboardEventSource.MoreDropdown
                                                                )
                                                            }
                                                            fullWidth
                                                        >
                                                            Edit layout (E)
                                                        </LemonButton>
                                                    )}

                                                    <LemonButton
                                                        onClick={() =>
                                                            setDashboardMode(
                                                                DashboardMode.Fullscreen,
                                                                DashboardEventSource.MoreDropdown
                                                            )
                                                        }
                                                        fullWidth
                                                    >
                                                        Go full screen (F)
                                                    </LemonButton>

                                                    {canEditDashboard &&
                                                        (dashboard.pinned ? (
                                                            <LemonButton
                                                                onClick={() =>
                                                                    unpinDashboard(
                                                                        dashboard.id,
                                                                        DashboardEventSource.MoreDropdown
                                                                    )
                                                                }
                                                                fullWidth
                                                            >
                                                                Unpin dashboard
                                                            </LemonButton>
                                                        ) : (
                                                            <LemonButton
                                                                onClick={() =>
                                                                    pinDashboard(
                                                                        dashboard.id,
                                                                        DashboardEventSource.MoreDropdown
                                                                    )
                                                                }
                                                                fullWidth
                                                            >
                                                                Pin dashboard
                                                            </LemonButton>
                                                        ))}
                                                    <SubscribeButton dashboardId={dashboard.id} />
                                                    <ExportButton fullWidth items={exportOptions} />
                                                    {user?.is_staff && (
                                                        <LemonButton
                                                            onClick={() => {
                                                                if (asDashboardTemplate) {
                                                                    setDashboardTemplate(asDashboardTemplate)
                                                                    openDashboardTemplateEditor()
                                                                }
                                                            }}
                                                            fullWidth
                                                        >
                                                            Save as template
                                                        </LemonButton>
                                                    )}
                                                    <LemonDivider />

                                                    <LemonButton
                                                        onClick={() => {
                                                            showDuplicateDashboardModal(dashboard.id, dashboard.name)
                                                        }}
                                                        fullWidth
                                                    >
                                                        Duplicate dashboard
                                                    </LemonButton>

                                                    <LemonButton
                                                        onClick={() => createNotebookFromDashboard(dashboard)}
                                                        fullWidth
                                                    >
                                                        Create notebook from dashboard
                                                    </LemonButton>

                                                    {canEditDashboard && (
                                                        <AccessControlledLemonButton
                                                            userAccessLevel={dashboard.user_access_level}
                                                            minAccessLevel={AccessControlLevel.Editor}
                                                            resourceType={AccessControlResourceType.Dashboard}
                                                            onClick={() => {
                                                                showDeleteDashboardModal(dashboard.id)
                                                            }}
                                                            status="danger"
                                                            fullWidth
                                                        >
                                                            Delete dashboard
                                                        </AccessControlledLemonButton>
                                                    )}
                                                </>
                                            ) : undefined
                                        }
                                    />
                                    <LemonDivider vertical />
                                </>
                            )}

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
                                    >
                                        Share
                                    </LemonButton>
                                </>
                            )}
                            {dashboard ? (
                                <AccessControlledLemonButton
                                    userAccessLevel={dashboard.user_access_level}
                                    minAccessLevel={AccessControlLevel.Editor}
                                    resourceType={AccessControlResourceType.Dashboard}
                                    onClick={showAddInsightToDashboardModal}
                                    type="primary"
                                    data-attr="dashboard-add-graph-header"
                                    sideAction={{
                                        dropdown: {
                                            placement: 'bottom-end',
                                            overlay: (
                                                <>
                                                    <AccessControlledLemonButton
                                                        userAccessLevel={dashboard.user_access_level}
                                                        minAccessLevel={AccessControlLevel.Editor}
                                                        resourceType={AccessControlResourceType.Dashboard}
                                                        fullWidth
                                                        onClick={() => {
                                                            push(urls.dashboardTextTile(dashboard.id, 'new'))
                                                        }}
                                                        data-attr="add-text-tile-to-dashboard"
                                                    >
                                                        Add text card
                                                    </AccessControlledLemonButton>
                                                </>
                                            ),
                                        },
                                        disabled: false,
                                        'data-attr': 'dashboard-add-dropdown',
                                    }}
                                >
                                    Add insight
                                </AccessControlledLemonButton>
                            ) : null}
                        </>
                    )
                }
                caption={
                    <>
                        {!newSceneLayout && dashboard && !!(canEditDashboard || dashboard.description) && (
                            <EditableField
                                multiline
                                name="description"
                                markdown
                                value={dashboard.description}
                                placeholder="Description (optional)"
                                onSave={(value) =>
                                    updateDashboard({ id: dashboard.id, description: value, allowUndo: true })
                                }
                                saveOnBlur={true}
                                compactButtons
                                mode={!canEditDashboard ? 'view' : undefined}
                            />
                        )}
                        {!newSceneLayout && dashboard?.tags && (
                            <>
                                {canEditDashboard ? (
                                    <ObjectTags
                                        tags={dashboard.tags}
                                        onChange={(tags) => triggerDashboardUpdate({ tags })}
                                        saving={dashboardLoading}
                                        tagsAvailable={tags.filter((tag) => !dashboard.tags?.includes(tag))}
                                        className="mt-2"
                                    />
                                ) : dashboard.tags.length ? (
                                    <ObjectTags
                                        tags={dashboard.tags}
                                        saving={dashboardLoading}
                                        staticOnly
                                        className="mt-2"
                                    />
                                ) : null}
                            </>
                        )}
                    </>
                }
            />

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
                <ScenePanelMetaInfo>
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
                </ScenePanelMetaInfo>
                <ScenePanelDivider />

                <ScenePanelActions>
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

                    {dashboard && canEditDashboard && (
                        <>
                            <ScenePanelDivider />
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
                        </>
                    )}
                </ScenePanelActions>
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
