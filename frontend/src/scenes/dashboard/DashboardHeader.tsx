import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { TextCardModal } from 'lib/components/Cards/TextCard/TextCardModal'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { ExportButton, ExportButtonItem } from 'lib/components/ExportButton/ExportButton'
import { FullScreen } from 'lib/components/FullScreen'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { PageHeader } from 'lib/components/PageHeader'
import { SharingModal } from 'lib/components/Sharing/SharingModal'
import { SubscribeButton, SubscriptionsModal } from 'lib/components/Subscriptions/SubscriptionsModal'
import { privilegeLevelToName } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { isLemonSelectSection } from 'lib/lemon-ui/LemonSelect'
import { ProfileBubbles } from 'lib/lemon-ui/ProfilePicture/ProfileBubbles'
import { humanFriendlyDetailedTime, slugify } from 'lib/utils'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { deleteDashboardLogic } from 'scenes/dashboard/deleteDashboardLogic'
import { DeleteDashboardModal } from 'scenes/dashboard/DeleteDashboardModal'
import { duplicateDashboardLogic } from 'scenes/dashboard/duplicateDashboardLogic'
import { DuplicateDashboardModal } from 'scenes/dashboard/DuplicateDashboardModal'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { dashboardsModel } from '~/models/dashboardsModel'
import { notebooksModel } from '~/models/notebooksModel'
import { tagsModel } from '~/models/tagsModel'
import { DashboardMode, DashboardType, ExporterFormat, QueryBasedInsightModel } from '~/types'

import { DASHBOARD_RESTRICTION_OPTIONS } from './DashboardCollaborators'
import { dashboardCollaboratorsLogic } from './dashboardCollaboratorsLogic'
import { dashboardLogic } from './dashboardLogic'
import { DashboardTemplateEditor } from './DashboardTemplateEditor'
import { dashboardTemplateEditorLogic } from './dashboardTemplateEditorLogic'

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

    const { setDashboardTemplate, openDashboardTemplateEditor } = useActions(dashboardTemplateEditorLogic)

    const { user } = useValues(userLogic)

    const { showDuplicateDashboardModal } = useActions(duplicateDashboardLogic)
    const { showDeleteDashboardModal } = useActions(deleteDashboardLogic)

    const { tags } = useValues(tagsModel)

    const { push } = useActions(router)

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
                                disabled={dashboardLoading}
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
                            <More
                                data-attr="dashboard-three-dots-options-menu"
                                overlay={
                                    dashboard ? (
                                        <>
                                            {dashboard.created_by && (
                                                <>
                                                    <div className="flex p-2 text-muted-alt">
                                                        Created by{' '}
                                                        {dashboard.created_by.first_name ||
                                                            dashboard.created_by.email ||
                                                            '-'}{' '}
                                                        on {humanFriendlyDetailedTime(dashboard.created_at)}
                                                    </div>
                                                    <LemonDivider />
                                                </>
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
                                                <LemonButton
                                                    onClick={() => {
                                                        showDeleteDashboardModal(dashboard.id)
                                                    }}
                                                    status="danger"
                                                    fullWidth
                                                >
                                                    Delete dashboard
                                                </LemonButton>
                                            )}
                                        </>
                                    ) : undefined
                                }
                            />
                            <LemonDivider vertical />
                            {dashboard && (
                                <>
                                    <CollaboratorBubbles
                                        dashboard={dashboard}
                                        onClick={() => push(urls.dashboardSharing(dashboard.id))}
                                    />
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
                                <LemonButton
                                    to={urls.insightNew(undefined, dashboard.id)}
                                    type="primary"
                                    data-attr="dashboard-add-graph-header"
                                    disabledReason={canEditDashboard ? null : DASHBOARD_CANNOT_EDIT_MESSAGE}
                                    sideAction={{
                                        dropdown: {
                                            placement: 'bottom-end',
                                            overlay: (
                                                <>
                                                    <LemonButton
                                                        fullWidth
                                                        onClick={() => {
                                                            push(urls.dashboardTextTile(dashboard.id, 'new'))
                                                        }}
                                                        data-attr="add-text-tile-to-dashboard"
                                                    >
                                                        Add text card
                                                    </LemonButton>
                                                </>
                                            ),
                                        },
                                        disabled: false,
                                        'data-attr': 'dashboard-add-dropdown',
                                    }}
                                >
                                    Add insight
                                </LemonButton>
                            ) : null}
                        </>
                    )
                }
                caption={
                    <>
                        {dashboard && !!(canEditDashboard || dashboard.description) && (
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
                        {dashboard?.tags && (
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
                delimited
            />
            <DashboardTemplateEditor />
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
