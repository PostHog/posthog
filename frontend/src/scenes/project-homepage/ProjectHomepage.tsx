import './ProjectHomepage.scss'

import { IconHome } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'
import useSize from '@react-hook/size'
import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneDashboardChoiceModal } from 'lib/components/SceneDashboardChoice/SceneDashboardChoiceModal'
import { sceneDashboardChoiceModalLogic } from 'lib/components/SceneDashboardChoice/sceneDashboardChoiceModalLogic'
import { SceneDashboardChoiceRequired } from 'lib/components/SceneDashboardChoice/SceneDashboardChoiceRequired'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useRef } from 'react'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { projectHomepageLogic } from 'scenes/project-homepage/projectHomepageLogic'
import { NewInsightButton } from 'scenes/saved-insights/SavedInsights'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { DashboardPlacement } from '~/types'

import { NewlySeenPersons } from './NewlySeenPersons'
import { RecentInsights } from './RecentInsights'
import { RecentRecordings } from './RecentRecordings'

export function ProjectHomepage(): JSX.Element {
    const { dashboardLogicProps } = useValues(projectHomepageLogic)
    const { currentTeam } = useValues(teamLogic)
    const { dashboard } = useValues(dashboardLogic(dashboardLogicProps))
    const { showInviteModal } = useActions(inviteLogic)
    const { showSceneDashboardChoiceModal } = useActions(
        sceneDashboardChoiceModalLogic({ scene: Scene.ProjectHomepage })
    )
    const { featureFlags } = useValues(featureFlagLogic)

    const topListContainerRef = useRef<HTMLDivElement | null>(null)
    const [topListContainerWidth] = useSize(topListContainerRef)

    const has3000 = featureFlags[FEATURE_FLAGS.POSTHOG_3000]

    const headerButtons = (
        <>
            <LemonButton
                data-attr="project-home-invite-team-members"
                onClick={() => {
                    showInviteModal()
                }}
                type="secondary"
            >
                Invite members
            </LemonButton>
            {!has3000 && <NewInsightButton dataAttr="project-home-new-insight" />}
        </>
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
                <>
                    <div className="HomepageDashboardHeader">
                        <div className="HomepageDashboardHeader__title">
                            {!dashboard && <LemonSkeleton className="w-20 h-4" />}
                            {dashboard?.name && (
                                <>
                                    <IconHome className="mr-2 text-2xl opacity-50" />
                                    <Link
                                        className="font-semibold text-xl text-default"
                                        to={urls.dashboard(dashboard.id)}
                                    >
                                        {dashboard?.name}
                                    </Link>
                                </>
                            )}
                        </div>
                        <div className="flex items-center gap-2">
                            <LemonButton
                                type="secondary"
                                size={has3000 ? 'small' : undefined}
                                data-attr="project-home-change-dashboard"
                                onClick={showSceneDashboardChoiceModal}
                            >
                                Change dashboard
                            </LemonButton>
                        </div>
                    </div>
                    <LemonDivider className={has3000 ? 'mt-3 mb-4' : 'my-4'} />
                    <Dashboard
                        id={currentTeam.primary_dashboard.toString()}
                        placement={DashboardPlacement.ProjectHomepage}
                    />
                </>
            ) : (
                <SceneDashboardChoiceRequired
                    open={() => {
                        showSceneDashboardChoiceModal()
                    }}
                    scene={Scene.ProjectHomepage}
                />
            )}
            <SceneDashboardChoiceModal scene={Scene.ProjectHomepage} />
        </div>
    )
}

export const scene: SceneExport = {
    component: ProjectHomepage,
    logic: projectHomepageLogic,
}
