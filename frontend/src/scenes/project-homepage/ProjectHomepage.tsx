import React from 'react'
import './ProjectHomepage.scss'
import { PageHeader } from 'lib/components/PageHeader'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { DashboardPlacement } from '~/types'
import { Row, Skeleton, Typography } from 'antd'
import { inviteLogic } from 'scenes/organization/Settings/inviteLogic'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { LemonSpacer } from 'lib/components/LemonRow'
import { PrimaryDashboardModal } from './PrimaryDashboardModal'
import { primaryDashboardModalLogic } from './primaryDashboardModalLogic'
import { IconCottage } from 'lib/components/icons'
import { projectHomepageLogic } from 'scenes/project-homepage/projectHomepageLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/components/LemonButton'
import { RecentRecordings } from './RecentRecordings'
import { RecentInsights } from './RecentInsights'

export function ProjectHomepage(): JSX.Element {
    const { dashboardLogic } = useValues(projectHomepageLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { currentTeam } = useValues(teamLogic)
    const { dashboard } = useValues(dashboardLogic)
    const { showInviteModal } = useActions(inviteLogic)
    const { showPrimaryDashboardModal } = useActions(primaryDashboardModalLogic)

    const headerButtons = (
        <div style={{ display: 'flex' }}>
            <LemonButton
                data-attr="project-home-invite-team-members"
                onClick={() => {
                    showInviteModal()
                }}
                className="mr-05"
                type="secondary"
            >
                Invite members
            </LemonButton>
            <LemonButton
                data-attr="project-home-new-insight"
                onClick={() => {
                    router.actions.push(urls.insightNew())
                }}
                type="secondary"
            >
                New insight
            </LemonButton>
        </div>
    )

    return (
        <div className="project-homepage">
            <PageHeader title={currentTeam?.name || ''} delimited buttons={headerButtons} />
            {featureFlags[FEATURE_FLAGS.HOMEPAGE_LISTS] && (
                <div className="top-list-container-horizontal">
                    <div className="top-list">
                        <RecentInsights />
                    </div>
                    <div className="spacer" />
                    <div className="top-list">
                        <RecentRecordings />
                    </div>
                    <div className="spacer" />
                </div>
            )}
            {currentTeam?.primary_dashboard ? (
                <div>
                    <div>
                        <Row className="homepage-dashboard-header">
                            <div className="dashboard-title-container">
                                {!dashboard && <Skeleton active paragraph={false} />}
                                {dashboard?.name && (
                                    <>
                                        <IconCottage className="mr-05 text-warning" style={{ fontSize: '1.5rem' }} />
                                        <Typography.Title className="dashboard-name" level={4}>
                                            {dashboard?.name}
                                        </Typography.Title>
                                    </>
                                )}
                            </div>
                            <LemonButton
                                type="secondary"
                                data-attr="project-home-new-insight"
                                onClick={showPrimaryDashboardModal}
                            >
                                Change dashboard
                            </LemonButton>
                        </Row>
                        <LemonSpacer large />
                    </div>
                    <Dashboard
                        id={currentTeam.primary_dashboard.toString()}
                        placement={DashboardPlacement.ProjectHomepage}
                    />
                </div>
            ) : (
                <div className="empty-state-container">
                    <IconCottage className="mb-05 text-warning" style={{ fontSize: '2rem' }} />
                    <h1>There isn’t a default dashboard set for this project</h1>
                    <p className="mb">
                        Default dashboards are shown to everyone in the project. When you set a default, it’ll show up
                        here.
                    </p>
                    <LemonButton
                        type="primary"
                        data-attr="project-home-new-insight"
                        onClick={() => {
                            showPrimaryDashboardModal()
                        }}
                    >
                        Select a default dashboard
                    </LemonButton>
                </div>
            )}
            <PrimaryDashboardModal />
        </div>
    )
}

export const scene: SceneExport = {
    component: ProjectHomepage,
    logic: projectHomepageLogic,
}
