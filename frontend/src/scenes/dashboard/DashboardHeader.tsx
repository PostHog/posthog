import { useActions, useValues } from 'kea'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { FullScreen } from 'lib/components/FullScreen'
import { LemonButton } from 'lib/components/LemonButton'
import { More } from 'lib/components/LemonButton/More'
import { LemonRow } from 'lib/components/LemonRow'
import { LemonDivider } from 'lib/components/LemonDivider'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { PageHeader } from 'lib/components/PageHeader'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import React, { useState } from 'react'
import { dashboardsModel } from '~/models/dashboardsModel'
import { AvailableFeature, DashboardMode, DashboardType } from '~/types'
import { dashboardLogic } from './dashboardLogic'
import { dashboardsLogic } from './dashboardsLogic'
import { DASHBOARD_RESTRICTION_OPTIONS, ShareModal } from './ShareModal'
import { userLogic } from 'scenes/userLogic'
import { FEATURE_FLAGS, privilegeLevelToName } from 'lib/constants'
import { ProfileBubbles } from 'lib/components/ProfilePicture/ProfileBubbles'
import { dashboardCollaboratorsLogic } from './dashboardCollaboratorsLogic'
import { IconLock } from 'lib/components/icons'
import { urls } from 'scenes/urls'
import { Link } from 'lib/components/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ExportButton } from 'lib/components/ExportButton/ExportButton'

export function DashboardHeader(): JSX.Element | null {
    const { dashboard, allItemsLoading, dashboardMode, canEditDashboard } = useValues(dashboardLogic)
    const { setDashboardMode, triggerDashboardUpdate } = useActions(dashboardLogic)
    const { dashboardTags } = useValues(dashboardsLogic)
    const { updateDashboard, pinDashboard, unpinDashboard, deleteDashboard, duplicateDashboard } =
        useActions(dashboardsModel)
    const { dashboardLoading } = useValues(dashboardsModel)
    const { hasAvailableFeature } = useValues(userLogic)

    const [isShareModalVisible, setIsShareModalVisible] = useState(false)

    const { featureFlags } = useValues(featureFlagLogic)
    const usingExportFeature = featureFlags[FEATURE_FLAGS.EXPORT_DASHBOARD_INSIGHTS]

    return dashboard || allItemsLoading ? (
        <>
            {dashboardMode === DashboardMode.Fullscreen && (
                <FullScreen onExit={() => setDashboardMode(null, DashboardEventSource.Browser)} />
            )}
            {dashboard && <ShareModal onCancel={() => setIsShareModalVisible(false)} visible={isShareModalVisible} />}
            <PageHeader
                title={
                    <div style={{ display: 'flex', alignItems: 'center' }}>
                        <EditableField
                            name="name"
                            value={dashboard?.name || (allItemsLoading ? 'Loading…' : '')}
                            placeholder="Name this dashboard"
                            onSave={
                                dashboard ? (value) => updateDashboard({ id: dashboard.id, name: value }) : undefined
                            }
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
                                overlay={
                                    dashboard ? (
                                        <>
                                            {dashboard.created_by && (
                                                <>
                                                    <LemonRow fullWidth style={{ color: 'var(--muted-alt)' }}>
                                                        Created by{' '}
                                                        {dashboard.created_by.first_name ||
                                                            dashboard.created_by.email ||
                                                            '-'}{' '}
                                                        on {humanFriendlyDetailedTime(dashboard.created_at)}
                                                    </LemonRow>
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
                                                    type="stealth"
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
                                                type="stealth"
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
                                                        type="stealth"
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
                                                        type="stealth"
                                                        fullWidth
                                                    >
                                                        Pin dashboard
                                                    </LemonButton>
                                                ))}
                                            {usingExportFeature && (
                                                <ExportButton dashboardId={dashboard.id} fullWidth type="stealth" />
                                            )}
                                            <LemonDivider />
                                            <LemonButton
                                                onClick={() =>
                                                    duplicateDashboard({
                                                        id: dashboard.id,
                                                        name: dashboard.name,
                                                        show: true,
                                                    })
                                                }
                                                type="stealth"
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
                                                    type="stealth"
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
                                <CollaboratorBubbles
                                    dashboard={dashboard}
                                    onClick={() => setIsShareModalVisible((state) => !state)}
                                />
                            )}
                            <LemonButton
                                type="secondary"
                                data-attr="dashboard-share-button"
                                onClick={() => setIsShareModalVisible((state) => !state)}
                            >
                                Share
                            </LemonButton>
                            {canEditDashboard && (
                                <Link to={urls.insightNew(undefined, dashboard?.id)}>
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
                        {dashboard && !!(canEditDashboard || dashboard.description) && (
                            <EditableField
                                multiline
                                name="description"
                                value={dashboard.description || ''}
                                placeholder="Description (optional)"
                                onSave={(value) => updateDashboard({ id: dashboard.id, description: value })}
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
    if (effectiveRestrictionLevelOption?.label) {
        tooltipParts.push(effectiveRestrictionLevelOption.label)
    }
    if (dashboard.is_shared) {
        tooltipParts.push('Shared publicly')
    }

    return (
        <ProfileBubbles
            people={allCollaborators.map((collaborator) => ({
                email: collaborator.user.email,
                name: collaborator.user.first_name,
                title: `${collaborator.user.first_name} (${privilegeLevelToName[collaborator.level]})`,
            }))}
            tooltip={tooltipParts.join(' • ')}
            onClick={onClick}
        />
    )
}
