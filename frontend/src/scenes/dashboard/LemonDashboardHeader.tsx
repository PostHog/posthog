import { useActions, useValues } from 'kea'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { FullScreen } from 'lib/components/FullScreen'
import { LemonButton } from 'lib/components/LemonButton'
import { More } from 'lib/components/LemonButton/More'
import { LemonRow, LemonSpacer } from 'lib/components/LemonRow'
import { ObjectTags } from 'lib/components/ObjectTags'
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
import { privilegeLevelToName } from 'lib/constants'
import { ProfileBubbles } from 'lib/components/ProfilePicture/ProfileBubbles'
import { dashboardCollaboratorsLogic } from './dashboardCollaboratorsLogic'

export function LemonDashboardHeader(): JSX.Element | null {
    const { dashboard, dashboardMode } = useValues(dashboardLogic)
    const { setDashboardMode, addGraph, saveNewTag, deleteTag } = useActions(dashboardLogic)
    const { dashboardTags } = useValues(dashboardsLogic)
    const { updateDashboard, pinDashboard, unpinDashboard, deleteDashboard, duplicateDashboard } =
        useActions(dashboardsModel)
    const { dashboardLoading } = useValues(dashboardsModel)
    const { hasAvailableFeature } = useValues(userLogic)

    const [isShareModalVisible, setIsShareModalVisible] = useState(false)

    return (
        dashboard && (
            <>
                {dashboardMode === DashboardMode.Fullscreen && (
                    <FullScreen onExit={() => setDashboardMode(null, DashboardEventSource.Browser)} />
                )}
                {dashboard && (
                    <ShareModal onCancel={() => setIsShareModalVisible(false)} visible={isShareModalVisible} />
                )}
                <PageHeader
                    title={
                        <EditableField
                            name="name"
                            value={dashboard.name || ''}
                            placeholder="Name this dashboard"
                            onSave={(value) => updateDashboard({ id: dashboard.id, name: value })}
                            minLength={1}
                            maxLength={400} // Sync with Dashboard model
                        />
                    }
                    buttons={
                        dashboardMode === DashboardMode.Edit ? (
                            <LemonButton
                                data-attr="dashboard-edit-mode-save"
                                type="primary"
                                onClick={() => setDashboardMode(null, DashboardEventSource.DashboardHeader)}
                                tabIndex={10}
                            >
                                Done editing
                            </LemonButton>
                        ) : dashboardMode === DashboardMode.Fullscreen ? (
                            <LemonButton
                                type="secondary"
                                onClick={() => setDashboardMode(null, DashboardEventSource.DashboardHeader)}
                                data-attr="dashboard-exit-presentation-mode"
                            >
                                Exit full screen
                            </LemonButton>
                        ) : (
                            <>
                                <More
                                    overlay={
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
                                                    <LemonSpacer />
                                                </>
                                            )}
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
                                            {dashboard.pinned ? (
                                                <LemonButton
                                                    onClick={() =>
                                                        unpinDashboard(dashboard.id, DashboardEventSource.MoreDropdown)
                                                    }
                                                    type="stealth"
                                                    fullWidth
                                                >
                                                    Unpin dashboard
                                                </LemonButton>
                                            ) : (
                                                <LemonButton
                                                    onClick={() =>
                                                        pinDashboard(dashboard.id, DashboardEventSource.MoreDropdown)
                                                    }
                                                    type="stealth"
                                                    fullWidth
                                                >
                                                    Pin dashboard
                                                </LemonButton>
                                            )}
                                            <LemonSpacer />
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
                                            <LemonButton
                                                onClick={() => deleteDashboard({ id: dashboard.id, redirect: true })}
                                                status="danger"
                                                type="stealth"
                                                fullWidth
                                            >
                                                Delete dashboard
                                            </LemonButton>
                                        </>
                                    }
                                />
                                <LemonSpacer vertical />
                                {dashboard && <CollaboratorBubbles dashboard={dashboard} />}
                                <LemonButton
                                    type="secondary"
                                    data-attr="dashboard-share-button"
                                    onClick={() => setIsShareModalVisible((state) => !state)}
                                >
                                    Share
                                </LemonButton>
                                <LemonButton
                                    type="primary"
                                    onClick={() => addGraph()}
                                    data-attr="dashboard-add-graph-header"
                                >
                                    New insight
                                </LemonButton>
                            </>
                        )
                    }
                    caption={
                        <>
                            <EditableField
                                multiline
                                name="description"
                                value={dashboard.description || ''}
                                placeholder="Description (optional)"
                                onSave={(value) => updateDashboard({ id: dashboard.id, description: value })}
                                compactButtons
                                isGated={!hasAvailableFeature(AvailableFeature.DASHBOARD_COLLABORATION)}
                            />
                            <ObjectTags
                                tags={dashboard.tags}
                                onTagSave={saveNewTag}
                                onTagDelete={deleteTag}
                                saving={dashboardLoading}
                                tagsAvailable={dashboardTags.filter((tag) => !dashboard.tags.includes(tag))}
                                className="insight-metadata-tags"
                            />
                        </>
                    }
                    delimited
                />
            </>
        )
    )
}

function CollaboratorBubbles({ dashboard }: { dashboard: DashboardType }): JSX.Element | null {
    const { allCollaborators } = useValues(dashboardCollaboratorsLogic({ dashboardId: dashboard.id }))

    if (!dashboard) {
        return null
    }

    const tooltipParts: string[] = [DASHBOARD_RESTRICTION_OPTIONS[dashboard.effective_restriction_level].label || '?']
    if (dashboard.is_shared) {
        tooltipParts.push('Shared publicly')
    }

    return (
        <ProfileBubbles
            people={allCollaborators.map((collaborator) => ({
                email: collaborator.user.email,
                name: collaborator.user.first_name,
                title: `${collaborator.user.first_name} (${privilegeLevelToName(collaborator.level)})`,
            }))}
            tooltip={tooltipParts.join(' • ')}
        />
    )
}
