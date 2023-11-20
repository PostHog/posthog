import { useActions, useValues } from 'kea'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { FullScreen } from 'lib/components/FullScreen'
import { LemonButton, LemonButtonWithSideAction } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { PageHeader } from 'lib/components/PageHeader'
import { humanFriendlyDetailedTime, slugify } from 'lib/utils'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { dashboardsModel } from '~/models/dashboardsModel'
import { AvailableFeature, DashboardMode, DashboardType, ExporterFormat } from '~/types'
import { dashboardLogic } from './dashboardLogic'
import { DASHBOARD_RESTRICTION_OPTIONS } from './DashboardCollaborators'
import { userLogic } from 'scenes/userLogic'
import { privilegeLevelToName } from 'lib/constants'
import { ProfileBubbles } from 'lib/lemon-ui/ProfilePicture/ProfileBubbles'
import { dashboardCollaboratorsLogic } from './dashboardCollaboratorsLogic'
import { IconLock } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'
import { ExportButton, ExportButtonItem } from 'lib/components/ExportButton/ExportButton'
import { SubscribeButton, SubscriptionsModal } from 'lib/components/Subscriptions/SubscriptionsModal'
import { router } from 'kea-router'
import { SharingModal } from 'lib/components/Sharing/SharingModal'
import { isLemonSelectSection } from 'lib/lemon-ui/LemonSelect'
import { TextCardModal } from 'lib/components/Cards/TextCard/TextCardModal'
import { DeleteDashboardModal } from 'scenes/dashboard/DeleteDashboardModal'
import { deleteDashboardLogic } from 'scenes/dashboard/deleteDashboardLogic'
import { DuplicateDashboardModal } from 'scenes/dashboard/DuplicateDashboardModal'
import { duplicateDashboardLogic } from 'scenes/dashboard/duplicateDashboardLogic'
import { tagsModel } from '~/models/tagsModel'
import { DashboardTemplateEditor } from './DashboardTemplateEditor'
import { dashboardTemplateEditorLogic } from './dashboardTemplateEditorLogic'
import { notebooksModel } from '~/models/notebooksModel'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'

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

    const { hasAvailableFeature, user } = useValues(userLogic)

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
                        title="Dashboard Permissions"
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
                title={
                    <div className="flex items-center">
                        <EditableField
                            name="name"
                            value={dashboard?.name || (dashboardLoading ? 'Loading…' : '')}
                            placeholder="Name this dashboard"
                            onSave={
                                dashboard
                                    ? (value) => updateDashboard({ id: dashboard.id, name: value, allowUndo: true })
                                    : undefined
                            }
                            saveOnBlur={true}
                            minLength={1}
                            maxLength={400} // Sync with Dashboard model
                            mode={!canEditDashboard ? 'view' : undefined}
                            notice={
                                dashboard && !canEditDashboard
                                    ? {
                                          icon: <IconLock />,
                                          tooltip: DASHBOARD_CANNOT_EDIT_MESSAGE,
                                      }
                                    : undefined
                            }
                            data-attr="dashboard-name"
                        />
                    </div>
                }
                buttons={
                    dashboardMode === DashboardMode.Edit ? (
                        <LemonButton
                            data-attr="dashboard-edit-mode-save"
                            type="primary"
                            onClick={() => setDashboardMode(null, DashboardEventSource.DashboardHeader)}
                            tabIndex={10}
                            disabled={dashboardLoading}
                        >
                            Done editing
                        </LemonButton>
                    ) : dashboardMode === DashboardMode.Fullscreen ? (
                        <LemonButton
                            type="secondary"
                            onClick={() => setDashboardMode(null, DashboardEventSource.DashboardHeader)}
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
                                                    status="stealth"
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
                                                status="stealth"
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
                                                        status="stealth"
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
                                                        status="stealth"
                                                        fullWidth
                                                    >
                                                        Pin dashboard
                                                    </LemonButton>
                                                ))}
                                            <SubscribeButton dashboardId={dashboard.id} />
                                            <ExportButton fullWidth status="stealth" items={exportOptions} />
                                            {user?.is_staff && (
                                                <LemonButton
                                                    onClick={() => {
                                                        if (asDashboardTemplate) {
                                                            setDashboardTemplate(asDashboardTemplate)
                                                            openDashboardTemplateEditor()
                                                        }
                                                    }}
                                                    fullWidth
                                                    status="stealth"
                                                >
                                                    Save as template
                                                </LemonButton>
                                            )}
                                            <LemonDivider />
                                            <LemonButton
                                                onClick={() => {
                                                    showDuplicateDashboardModal(dashboard.id, dashboard.name)
                                                }}
                                                status="stealth"
                                                fullWidth
                                            >
                                                Duplicate dashboard
                                            </LemonButton>
                                            <FlaggedFeature flag={'notebooks'}>
                                                <LemonButton
                                                    onClick={() => createNotebookFromDashboard(dashboard)}
                                                    status="stealth"
                                                    fullWidth
                                                >
                                                    Create notebook from dashboard
                                                </LemonButton>
                                            </FlaggedFeature>
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
                                <LemonButtonWithSideAction
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
                                                        status="stealth"
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
                                </LemonButtonWithSideAction>
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
                                value={dashboard.description || ''}
                                placeholder="Description (optional)"
                                onSave={(value) =>
                                    updateDashboard({ id: dashboard.id, description: value, allowUndo: true })
                                }
                                saveOnBlur={true}
                                compactButtons
                                mode={!canEditDashboard ? 'view' : undefined}
                                paywall={!hasAvailableFeature(AvailableFeature.DASHBOARD_COLLABORATION)}
                            />
                        )}
                        {dashboard?.tags && (
                            <>
                                {canEditDashboard ? (
                                    <ObjectTags
                                        tags={dashboard.tags}
                                        onChange={(_, tags) => triggerDashboardUpdate({ tags })}
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
    dashboard: DashboardType
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
