import { useActions, useValues } from 'kea'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { FullScreen } from 'lib/components/FullScreen'
import { LemonButton, LemonButtonWithSideAction } from 'lib/components/LemonButton'
import { More } from 'lib/components/LemonButton/More'
import { LemonDivider } from 'lib/components/LemonDivider'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { PageHeader } from 'lib/components/PageHeader'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { dashboardsModel } from '~/models/dashboardsModel'
import { AvailableFeature, DashboardMode, DashboardType, ExporterFormat } from '~/types'
import { dashboardLogic } from './dashboardLogic'
import { dashboardsLogic } from './dashboardsLogic'
import { DASHBOARD_RESTRICTION_OPTIONS } from './DashboardCollaborators'
import { userLogic } from 'scenes/userLogic'
import { FEATURE_FLAGS, privilegeLevelToName } from 'lib/constants'
import { ProfileBubbles } from 'lib/components/ProfilePicture/ProfileBubbles'
import { dashboardCollaboratorsLogic } from './dashboardCollaboratorsLogic'
import { IconLock } from 'lib/components/icons'
import { urls } from 'scenes/urls'
import { ExportButton } from 'lib/components/ExportButton/ExportButton'
import { SubscribeButton, SubscriptionsModal } from 'lib/components/Subscriptions/SubscriptionsModal'
import { router } from 'kea-router'
import { SharingModal } from 'lib/components/Sharing/SharingModal'
import { isLemonSelectSection } from 'lib/components/LemonSelect'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import { TextCardModal } from 'lib/components/Cards/TextCard/TextCardModal'

export function DashboardHeader(): JSX.Element | null {
    const {
        allItems: dashboard, // dashboard but directly on dashboardLogic not via dashboardsModel
        allItemsLoading: dashboardLoading,
        dashboardMode,
        canEditDashboard,
        showSubscriptions,
        subscriptionId,
        apiUrl,
        showTextTileModal,
        textTileId,
    } = useValues(dashboardLogic)
    const { setDashboardMode, triggerDashboardUpdate } = useActions(dashboardLogic)
    const { dashboardTags } = useValues(dashboardsLogic)
    const { updateDashboard, pinDashboard, unpinDashboard, deleteDashboard, duplicateDashboard } =
        useActions(dashboardsModel)

    const { hasAvailableFeature } = useValues(userLogic)

    const { push } = useActions(router)

    const { featureFlags } = useValues(featureFlagLogic)
    const showTextCards = featureFlags[FEATURE_FLAGS.TEXT_CARDS]

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
                        isOpen={dashboardMode === DashboardMode.Sharing}
                        closeModal={() => push(urls.dashboard(dashboard.id))}
                        dashboardId={dashboard.id}
                    />
                    {showTextCards && (
                        <TextCardModal
                            isOpen={showTextTileModal}
                            onClose={() => push(urls.dashboard(dashboard.id))}
                            dashboard={dashboard}
                            textTileId={textTileId}
                        />
                    )}
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
                                          tooltip:
                                              "You don't have edit permissions in this dashboard. Ask a dashboard collaborator with edit access to add you.",
                                      }
                                    : undefined
                            }
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
                                            <ExportButton
                                                fullWidth
                                                status="stealth"
                                                items={[
                                                    {
                                                        export_format: ExporterFormat.PNG,
                                                        dashboard: dashboard?.id,
                                                        export_context: {
                                                            path: apiUrl(),
                                                        },
                                                    },
                                                ]}
                                            />
                                            <LemonDivider />
                                            <LemonButton
                                                onClick={() =>
                                                    duplicateDashboard({
                                                        id: dashboard.id,
                                                        name: dashboard.name,
                                                        show: true,
                                                    })
                                                }
                                                status="stealth"
                                                fullWidth
                                            >
                                                Duplicate dashboard
                                            </LemonButton>
                                            {canEditDashboard && (
                                                <LemonButton
                                                    onClick={() =>
                                                        deleteDashboard({ id: dashboard.id, redirect: true })
                                                    }
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
                            {dashboard && canEditDashboard ? (
                                showTextCards && hasAvailableFeature(AvailableFeature.DASHBOARD_COLLABORATION) ? (
                                    <LemonButtonWithSideAction
                                        to={urls.insightNew(undefined, dashboard.id)}
                                        type="primary"
                                        data-attr="dashboard-add-graph-header"
                                        sideAction={{
                                            popup: {
                                                placement: 'bottom-end',
                                                overlay: (
                                                    <>
                                                        {showTextCards &&
                                                            hasAvailableFeature(
                                                                AvailableFeature.DASHBOARD_COLLABORATION
                                                            ) && (
                                                                <LemonButton
                                                                    status="stealth"
                                                                    fullWidth
                                                                    onClick={() => {
                                                                        push(
                                                                            urls.dashboardTextTile(dashboard.id, 'new')
                                                                        )
                                                                    }}
                                                                    data-attr="add-text-tile-to-dashboard"
                                                                >
                                                                    Add text card &nbsp;
                                                                    <LemonTag type="warning">BETA</LemonTag>
                                                                </LemonButton>
                                                            )}
                                                    </>
                                                ),
                                            },
                                            disabled: false,
                                            'data-attr': 'dashboard-add-dropdown',
                                        }}
                                    >
                                        Add insight
                                    </LemonButtonWithSideAction>
                                ) : (
                                    <LemonButton
                                        to={urls.insightNew(undefined, dashboard?.id)}
                                        type="primary"
                                        data-attr="dashboard-add-graph-header"
                                    >
                                        Add insight
                                    </LemonButton>
                                )
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
                                        tagsAvailable={dashboardTags.filter((tag) => !dashboard.tags?.includes(tag))}
                                        className="insight-metadata-tags"
                                    />
                                ) : dashboard.tags.length ? (
                                    <ObjectTags
                                        tags={dashboard.tags}
                                        saving={dashboardLoading}
                                        staticOnly
                                        className="insight-metadata-tags"
                                    />
                                ) : null}
                            </>
                        )}
                    </>
                }
                delimited
            />
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
