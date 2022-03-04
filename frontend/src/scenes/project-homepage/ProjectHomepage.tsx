import React from 'react'
import { PageHeader } from 'lib/components/PageHeader'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { DashboardLocation, InsightType } from '~/types'
import { Button, Row, Typography } from 'antd'
import { inviteLogic } from 'scenes/organization/Settings/inviteLogic'
import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { LemonSpacer } from 'lib/components/LemonRow'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { PrimaryDashboardModal } from './PrimaryDashboardModal'
import { primaryDashboardModalLogic } from './primaryDashboardModalLogic'

export function ProjectHomepage(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const dashboardLogicInstance = dashboardLogic({ id: currentTeam?.primary_dashboard ?? undefined })
    const { dashboard, allItemsLoading } = useValues(dashboardLogicInstance)
    const { closeSitePopover } = useActions(navigationLogic)
    const { showInviteModal } = useActions(inviteLogic)
    const { showPrimaryDashboardModal } = useActions(primaryDashboardModalLogic)

    const headerButtons = (
        <div style={{ display: 'flex' }}>
            <Button
                data-attr="project-home-invite-team-members"
                onClick={() => {
                    closeSitePopover()
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
                    {dashboard && !allItemsLoading && (
                        <div>
                            <Row style={{ justifyContent: 'space-between' }}>
                                <Typography.Title level={4}>{dashboard?.name}</Typography.Title>
                                <Button
                                    data-attr="project-home-new-insight"
                                    onClick={() => {
                                        showPrimaryDashboardModal()
                                    }}
                                >
                                    Change dashboard
                                </Button>
                            </Row>
                            <LemonSpacer />
                        </div>
                    )}
                    <Dashboard
                        id={currentTeam.primary_dashboard.toString()}
                        location={DashboardLocation.ProjectHomepage}
                    />
                </div>
            ) : (
                <div>
                    <h1>Set the default dashboard for this project</h1>
                </div>
            )}
            <PrimaryDashboardModal />
        </div>
    )
}

export const scene: SceneExport = {
    component: ProjectHomepage,
}
