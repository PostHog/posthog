import './ProjectHomepage.scss'

import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconHome } from '@posthog/icons'

import { SceneDashboardChoiceRequired } from 'lib/components/SceneDashboardChoice/SceneDashboardChoiceRequired'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { cn } from 'lib/utils/css-classes'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { DashboardLogicProps, dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { NewTabScene } from 'scenes/new-tab/NewTabScene'
import { projectHomepageLogic } from 'scenes/project-homepage/projectHomepageLogic'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { urls } from 'scenes/urls'

import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { DashboardPlacement } from '~/types'

import { AiFirstHomepage } from './ai-first/AiFirstHomepage'

export const scene: SceneExport = {
    component: ProjectHomepage,
    logic: projectHomepageLogic,
}

function HomePageContent(): JSX.Element {
    const { dashboardLogicProps } = useValues(projectHomepageLogic)
    const { showInviteModal } = useActions(inviteLogic)
    const { dashboard } = useValues(dashboardLogic(dashboardLogicProps as DashboardLogicProps))
    const { showConfigurePinnedTabsModal } = useActions(navigationLogic)

    // TODO: Remove this after AA test is over
    const { featureFlags } = useValues(featureFlagLogic)
    const aaTestBayesianLegacy = featureFlags[FEATURE_FLAGS.AA_TEST_BAYESIAN_LEGACY]
    const aaTestBayesianNew = featureFlags[FEATURE_FLAGS.AA_TEST_BAYESIAN_NEW]
    const isAiFirst = featureFlags[FEATURE_FLAGS.AI_FIRST]

    return (
        <SceneContent className={cn('ProjectHomepage', !isAiFirst && 'p-4')}>
            {/* TODO: Remove this after AA test is over. Just a hidden element. */}
            <span className="hidden" data-attr="aa-test-flag-result">
                AA test flag result: {String(aaTestBayesianLegacy)} {String(aaTestBayesianNew)}
            </span>

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
                            onClick={() => showConfigurePinnedTabsModal()}
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
            {dashboardLogicProps ? (
                <Dashboard id={dashboardLogicProps.id.toString()} placement={DashboardPlacement.ProjectHomepage} />
            ) : (
                <SceneDashboardChoiceRequired
                    open={() => {
                        showConfigurePinnedTabsModal()
                    }}
                    scene={Scene.ProjectHomepage}
                />
            )}
        </SceneContent>
    )
}

export function ProjectHomepage(): JSX.Element {
    const { dashboardLogicProps } = useValues(projectHomepageLogic)
    const isAIFirst = useFeatureFlag('AI_FIRST')

    if (isAIFirst) {
        return (
            <div className="flex-1 min-h-0">
                <AiFirstHomepage />
            </div>
        )
    }

    // if there is no numeric dashboard id, the dashboard logic will throw...
    // so we check it here first
    if (dashboardLogicProps?.id) {
        return <HomePageContent />
    }
    // Negative margin to counter-act the scene configs default padding
    return (
        <div className="-m-4">
            <NewTabScene />
        </div>
    )
}
