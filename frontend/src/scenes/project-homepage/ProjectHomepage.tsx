import React from 'react'
import './ProjectHomepage.scss'
import { PageHeader } from 'lib/components/PageHeader'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { DashboardPlacement, InsightType } from '~/types'
import { Button, Row, Typography } from 'antd'
import { inviteLogic } from 'scenes/organization/Settings/inviteLogic'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { LemonSpacer } from 'lib/components/LemonRow'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { PrimaryDashboardModal } from './PrimaryDashboardModal'
import { primaryDashboardModalLogic } from './primaryDashboardModalLogic'
import { HomeIcon } from 'lib/components/icons'

export function ProjectHomepage(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const dashboardLogicInstance = dashboardLogic({ id: currentTeam?.primary_dashboard ?? undefined })
    const { dashboard } = useValues(dashboardLogicInstance)
    const { showInviteModal } = useActions(inviteLogic)
    const { showPrimaryDashboardModal } = useActions(primaryDashboardModalLogic)

    const headerButtons = (
        <div style={{ display: 'flex' }}>
            <Button
                data-attr="project-home-invite-team-members"
                onClick={() => {
                    showInviteModal()
                }}
                className="mr-05"
            >
                Invite members
            </Button>
            <Button
                data-attr="project-home-new-insight"
                onClick={() => {
                    router.actions.push(urls.insightNew({ insight: InsightType.TRENDS }))
                }}
            >
                New insight
            </Button>
        </div>
    )

    return (
        <div className="project-homepage">
            <PageHeader title={currentTeam?.name || ''} delimited buttons={headerButtons} />
            {currentTeam?.primary_dashboard ? (
                <div>
                    <div>
                        <Row className="dashboard-header">
                            <div className="dashboard-title-container">
                                <HomeIcon className="mr-05" style={{ width: 18 }} />
                                <Typography.Title className="dashboard-name" level={4}>
                                    {dashboard?.name}
                                </Typography.Title>
                            </div>
                            <Button data-attr="project-home-new-insight" onClick={showPrimaryDashboardModal}>
                                Change dashboard
                            </Button>
                        </Row>
                        <LemonSpacer />
                    </div>
                    <Dashboard
                        id={currentTeam.primary_dashboard.toString()}
                        placement={DashboardPlacement.ProjectHomepage}
                    />
                </div>
            ) : (
                <div className="empty-state-container">
                    <HomeIcon className="mb" />
                    <h1>There isn’t a default dashboard set for this project</h1>
                    <p className="mb">
                        Default dashboards are shown to everyone in the project. When you set a default, it’ll show up
                        here.
                    </p>
                    <Button
                        type="primary"
                        data-attr="project-home-new-insight"
                        onClick={() => {
                            showPrimaryDashboardModal()
                        }}
                    >
                        Select a default dashboard
                    </Button>
                </div>
            )}
            <PrimaryDashboardModal />
        </div>
    )
}

export const scene: SceneExport = {
    component: ProjectHomepage,
}
