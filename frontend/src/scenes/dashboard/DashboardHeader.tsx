import { useActions, useValues } from 'kea'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { FullScreen } from 'lib/components/FullScreen'
import { LemonButton } from 'lib/components/LemonButton'
import { More } from 'lib/components/LemonButton/More'
import { LemonDivider } from 'lib/components/LemonDivider'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { PageHeader } from 'lib/components/PageHeader'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import React from 'react'
import { dashboardsModel } from '~/models/dashboardsModel'
import { AvailableFeature, DashboardMode, DashboardType, ExporterFormat } from '~/types'
import { dashboardLogic } from './dashboardLogic'
import { dashboardsLogic } from './dashboardsLogic'
import { DASHBOARD_RESTRICTION_OPTIONS } from './DashboardCollaborators'
import { userLogic } from 'scenes/userLogic'
import { privilegeLevelToName } from 'lib/constants'
import { ProfileBubbles } from 'lib/components/ProfilePicture/ProfileBubbles'
import { dashboardCollaboratorsLogic } from './dashboardCollaboratorsLogic'
import { IconLock } from 'lib/components/icons'
import { urls } from 'scenes/urls'
import { Link } from 'lib/components/Link'
import { ExportButton } from 'lib/components/ExportButton/ExportButton'
import { SubscribeButton, SubscriptionsModal } from 'lib/components/Subscriptions/SubscriptionsModal'
import { router } from 'kea-router'
import { SharingModal } from 'lib/components/Sharing/SharingModal'
import { isLemonSelectSection } from 'lib/components/LemonSelect'

export function DashboardHeader(): JSX.Element | null {
    const { allItems, allItemsLoading, dashboardMode, canEditDashboard, showSubscriptions, subscriptionId, apiUrl } =
        useValues(dashboardLogic)
    const { setDashboardMode, updateDashboard } = useActions(dashboardLogic)
    const { dashboardTags } = useValues(dashboardsLogic)
    const { pinDashboard, unpinDashboard, deleteDashboard, duplicateDashboard } = useActions(dashboardsModel)
    const { dashboardLoading } = useValues(dashboardsModel)
    const { hasAvailableFeature } = useValues(userLogic)

    const { push } = useActions(router)

    return allItems || allItemsLoading ? (
        <>
            {dashboardMode === DashboardMode.Fullscreen && (
                <FullScreen onExit={() => setDashboardMode(null, DashboardEventSource.Browser)} />
            )}
            {allItems && (
                <>
                    <SubscriptionsModal
                        isOpen={showSubscriptions}
                        closeModal={() => push(urls.dashboard(allItems.id))}
                        dashboardId={allItems.id}
                        subscriptionId={subscriptionId}
                    />
                    <SharingModal
                        isOpen={dashboardMode === DashboardMode.Sharing}
                        closeModal={() => push(urls.dashboard(allItems.id))}
                        dashboardId={allItems.id}
                    />
                </>
            )}

            <PageHeader
                title={
                    <div className="flex items-center">
                        <EditableField
                            name="name"
                            value={allItems?.name || (allItemsLoading ? 'Loading…' : '')}
                            placeholder="Name this dashboard"
                            onSave={
                                allItems
                                    ? (value) => updateDashboard({ id: allItems.id, name: value, allowUndo: true })
                                    : undefined
                            }
                            saveOnBlur={true}
                            minLength={1}
                            maxLength={400} // Sync with Dashboard model
                            mode={!canEditDashboard ? 'view' : undefined}
                            notice={
                                allItems && !canEditDashboard
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
                            disabled={allItemsLoading}
                        >
                            Done editing
                        </LemonButton>
                    ) : dashboardMode === DashboardMode.Fullscreen ? (
                        <LemonButton
                            type="secondary"
                            onClick={() => setDashboardMode(null, DashboardEventSource.DashboardHeader)}
                            data-attr="dashboard-exit-presentation-mode"
                            disabled={allItemsLoading}
                        >
                            Exit full screen
                        </LemonButton>
                    ) : (
                        <>
                            <More
                                data-attr="dashboard-three-dots-options-menu"
                                overlay={
                                    allItems ? (
                                        <>
                                            {allItems.created_by && (
                                                <>
                                                    <div className="flex p-2 text-muted-alt">
                                                        Created by{' '}
                                                        {allItems.created_by.first_name ||
                                                            allItems.created_by.email ||
                                                            '-'}{' '}
                                                        on {humanFriendlyDetailedTime(allItems.created_at)}
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
                                                (allItems.pinned ? (
                                                    <LemonButton
                                                        onClick={() =>
                                                            unpinDashboard(
                                                                allItems.id,
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
                                                            pinDashboard(allItems.id, DashboardEventSource.MoreDropdown)
                                                        }
                                                        status="stealth"
                                                        fullWidth
                                                    >
                                                        Pin dashboard
                                                    </LemonButton>
                                                ))}
                                            <SubscribeButton dashboardId={allItems.id} />
                                            <ExportButton
                                                fullWidth
                                                status="stealth"
                                                items={[
                                                    {
                                                        export_format: ExporterFormat.PNG,
                                                        dashboard: allItems?.id,
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
                                                        id: allItems.id,
                                                        name: allItems.name,
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
                                                    onClick={() => deleteDashboard({ id: allItems.id, redirect: true })}
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
                            {allItems && (
                                <>
                                    <CollaboratorBubbles
                                        dashboard={allItems}
                                        onClick={() => push(urls.dashboardSharing(allItems.id))}
                                    />
                                    <LemonButton
                                        type="secondary"
                                        data-attr="dashboard-share-button"
                                        onClick={() => push(urls.dashboardSharing(allItems.id))}
                                    >
                                        Share
                                    </LemonButton>
                                </>
                            )}
                            {canEditDashboard && (
                                <Link to={urls.insightNew(undefined, allItems?.id)}>
                                    <LemonButton type="primary" data-attr="dashboard-add-graph-header">
                                        Add insight
                                    </LemonButton>
                                </Link>
                            )}
                        </>
                    )
                }
                caption={
                    <>
                        {allItems && !!(canEditDashboard || allItems.description) && (
                            <EditableField
                                multiline
                                name="description"
                                value={allItems.description || ''}
                                placeholder="Description (optional)"
                                onSave={(value) =>
                                    updateDashboard({ id: allItems.id, description: value, allowUndo: true })
                                }
                                saveOnBlur={true}
                                compactButtons
                                mode={!canEditDashboard ? 'view' : undefined}
                                paywall={!hasAvailableFeature(AvailableFeature.DASHBOARD_COLLABORATION)}
                            />
                        )}
                        {allItems?.tags && (
                            <>
                                {canEditDashboard ? (
                                    <ObjectTags
                                        tags={allItems.tags}
                                        onChange={(_, tags) => updateDashboard({ tags })}
                                        saving={dashboardLoading}
                                        tagsAvailable={dashboardTags.filter((tag) => !allItems.tags?.includes(tag))}
                                        className="insight-metadata-tags"
                                    />
                                ) : allItems.tags.length ? (
                                    <ObjectTags
                                        tags={allItems.tags}
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
