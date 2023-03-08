import { useRef } from 'react'
import './ProjectHomepage.scss'
import { PageHeader } from 'lib/components/PageHeader'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { DashboardPlacement } from '~/types'
import { inviteLogic } from 'scenes/organization/Settings/inviteLogic'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { PrimaryDashboardModal } from './PrimaryDashboardModal'
import { primaryDashboardModalLogic } from './primaryDashboardModalLogic'
import { IconCottage } from 'lib/lemon-ui/icons'
import { projectHomepageLogic } from 'scenes/project-homepage/projectHomepageLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { RecentRecordings } from './RecentRecordings'
import { RecentInsights } from './RecentInsights'
import { NewlySeenPersons } from './NewlySeenPersons'
import useSize from '@react-hook/size'
import { NewInsightButton } from 'scenes/saved-insights/SavedInsights'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Link } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

export function ProjectHomepage(): JSX.Element {
    const { dashboardLogicProps } = useValues(projectHomepageLogic)
    const { currentTeam } = useValues(teamLogic)
    const {
        allItems: dashboard, // dashboard but directly on dashboardLogic not via dashboardsModel
    } = useValues(dashboardLogic(dashboardLogicProps))
    const { showInviteModal } = useActions(inviteLogic)
    const { showPrimaryDashboardModal } = useActions(primaryDashboardModalLogic)
    const topListContainerRef = useRef<HTMLDivElement | null>(null)
    const [topListContainerWidth] = useSize(topListContainerRef)

    const headerButtons = (
        <div className="flex">
            <LemonButton
                data-attr="project-home-invite-team-members"
                onClick={() => {
                    showInviteModal()
                }}
                className="mr-2"
                type="secondary"
            >
                Invite members
            </LemonButton>
            <NewInsightButton dataAttr="project-home-new-insight" />
        </div>
    )

    return (
        <div className="project-homepage">
            <PageHeader title={currentTeam?.name || ''} delimited buttons={headerButtons} />
            <div
                ref={topListContainerRef}
                className={
                    topListContainerWidth && topListContainerWidth < 600
                        ? 'top-list-container-vertical'
                        : 'top-list-container-horizontal'
                }
            >
                <div className="top-list">
                    <RecentInsights />
                </div>
                <div className="spacer" />
                <div className="top-list">
                    <NewlySeenPersons />
                </div>
                <div className="spacer" />
                <div className="top-list">
                    <RecentRecordings />
                </div>
            </div>
            {currentTeam?.primary_dashboard ? (
                <div>
                    <div className="homepage-dashboard-header">
                        <div className="dashboard-title-container">
                            {!dashboard && <LemonSkeleton className="w-20" />}
                            {dashboard?.name && (
                                <>
                                    <IconCottage className="mr-2 text-warning text-2xl" />
                                    <Link
                                        className="font-semibold text-xl text-default"
                                        to={urls.dashboard(dashboard.id)}
                                    >
                                        {dashboard?.name}
                                    </Link>
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
                    </div>
                    <LemonDivider className="my-6" />
                    <Dashboard
                        id={currentTeam.primary_dashboard.toString()}
                        placement={DashboardPlacement.ProjectHomepage}
                    />
                </div>
            ) : (
                <div className="empty-state-container">
                    <IconCottage className="mb-2 text-warning" style={{ fontSize: '2rem' }} />
                    <h1>There isn’t a default dashboard set for this project</h1>
                    <p className="mb-4">
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
