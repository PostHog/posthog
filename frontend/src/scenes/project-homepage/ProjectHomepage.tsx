import './ProjectHomepage.scss'

import { IconHome } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'
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
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { projectHomepageLogic } from 'scenes/project-homepage/projectHomepageLogic'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { YearInHogButton } from '~/layout/navigation/TopBar/YearInHogButton'
import { DashboardPlacement } from '~/types'

import { RecentInsights } from './RecentInsights'
import { RecentPersons } from './RecentPersons'
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

    const headerButtons = (
        <>
            {!!featureFlags[FEATURE_FLAGS.YEAR_IN_HOG] && window.POSTHOG_APP_CONTEXT?.year_in_hog_url && (
                <YearInHogButton url={`${window.location.origin}${window.POSTHOG_APP_CONTEXT.year_in_hog_url}`} />
            )}
            <LemonButton
                type="secondary"
                size="small"
                data-attr="project-home-customize-homepage"
                onClick={showSceneDashboardChoiceModal}
            >
                Customize homepage
            </LemonButton>
            <LemonButton
                data-attr="project-home-invite-team-members"
                onClick={() => {
                    showInviteModal()
                }}
                type="secondary"
            >
                Invite members
            </LemonButton>
        </>
    )

    return (
        <div className="ProjectHomepage">
            <PageHeader delimited buttons={headerButtons} />
            <div className="ProjectHomepage__lists">
                <RecentInsights />
                <RecentPersons />
                <RecentRecordings />
            </div>
            {currentTeam?.primary_dashboard ? (
                <>
                    <div className="ProjectHomepage__dashboardheader">
                        <div className="ProjectHomepage__dashboardheader__title">
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
                    </div>
                    <LemonDivider className="mt-3 mb-4" />
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
