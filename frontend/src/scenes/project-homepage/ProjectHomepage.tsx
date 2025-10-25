import './ProjectHomepage.scss'

import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconHome } from '@posthog/icons'

import { SceneDashboardChoiceModal } from 'lib/components/SceneDashboardChoice/SceneDashboardChoiceModal'
import { SceneDashboardChoiceRequired } from 'lib/components/SceneDashboardChoice/SceneDashboardChoiceRequired'
import { sceneDashboardChoiceModalLogic } from 'lib/components/SceneDashboardChoice/sceneDashboardChoiceModalLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { DashboardLogicProps, dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { NewTabScene } from 'scenes/new-tab/NewTabScene'
import { projectHomepageLogic } from 'scenes/project-homepage/projectHomepageLogic'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { DashboardPlacement } from '~/types'

export const scene: SceneExport = {
    component: ProjectHomepage,
    logic: projectHomepageLogic,
}

function HomePageContent(): JSX.Element {
    const { dashboardLogicProps } = useValues(projectHomepageLogic)
    const { showInviteModal } = useActions(inviteLogic)
    const { showSceneDashboardChoiceModal } = useActions(
        sceneDashboardChoiceModalLogic({ scene: Scene.ProjectHomepage })
    )
    const { dashboard } = useValues(dashboardLogic(dashboardLogicProps as DashboardLogicProps))

    // TODO: Remove this after AA test is over
    const { featureFlags } = useValues(featureFlagLogic)
    const aaTestBayesianLegacy = featureFlags[FEATURE_FLAGS.AA_TEST_BAYESIAN_LEGACY]
    const aaTestBayesianNew = featureFlags[FEATURE_FLAGS.AA_TEST_BAYESIAN_NEW]

    // #team-ingestion/nickbest TODO: remove after person database migration tests are complete
    const personReadTestFlag = featureFlags[FEATURE_FLAGS.PERSON_READ_TEST_FLAG]

    return (
        <SceneContent className="ProjectHomepage">
            {/* TODO: Remove this after AA test is over. Just a hidden element. */}
            <span className="hidden" data-attr="aa-test-flag-result">
                AA test flag result: {String(aaTestBayesianLegacy)} {String(aaTestBayesianNew)}
            </span>

            {/* Hidden element for person read feature flag validation */}
            {personReadTestFlag && (
                <span className="hidden" data-attr="person-read-test-flag-active">
                    Person read test flag is active: {String(personReadTestFlag)}
                </span>
            )}

            <SceneTitleSection
                name={dashboard?.name ?? 'Project Homepage'}
                resourceType={{
                    type: 'project',
                    forceIcon: <IconHome />,
                }}
                actions={
                    <>
                        <LemonButton
                            type="secondary"
                            size="small"
                            data-attr="project-home-edit-dashboard"
                            onClick={() => {
                                router.actions.push(urls.dashboard(dashboard?.id ?? ''))
                            }}
                        >
                            View dashboard
                        </LemonButton>
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
                            size="small"
                        >
                            Invite members
                        </LemonButton>
                    </>
                }
            />
            <div>
                <SceneDivider />
                {dashboardLogicProps ? (
                    <Dashboard id={dashboardLogicProps.id.toString()} placement={DashboardPlacement.ProjectHomepage} />
                ) : (
                    <SceneDashboardChoiceRequired
                        open={() => {
                            showSceneDashboardChoiceModal()
                        }}
                        scene={Scene.ProjectHomepage}
                    />
                )}
            </div>
            <SceneDashboardChoiceModal scene={Scene.ProjectHomepage} />
        </SceneContent>
    )
}

export function ProjectHomepage(): JSX.Element {
    const { dashboardLogicProps } = useValues(projectHomepageLogic)
    // if there is no numeric dashboard id, the dashboard logic will throw...
    // so we check it here first
    if (dashboardLogicProps?.id) {
        // We add padding because the scene has layout: 'app-raw'
        return (
            <div className="p-4">
                <HomePageContent />
            </div>
        )
    }
    return <NewTabScene source="homepage" />
}
