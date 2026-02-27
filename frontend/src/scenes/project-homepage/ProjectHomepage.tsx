import './ProjectHomepage.scss'

import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconHome } from '@posthog/icons'

import { SceneDashboardChoiceRequired } from 'lib/components/SceneDashboardChoice/SceneDashboardChoiceRequired'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { DashboardLogicProps, dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { EventDefinitionModal } from 'scenes/data-management/events/EventDefinitionModal'
import { NewTabScene } from 'scenes/new-tab/NewTabScene'
import { projectHomepageLogic } from 'scenes/project-homepage/projectHomepageLogic'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ConfigurePinnedTabsModal } from '~/layout/scenes/ConfigurePinnedTabsModal'
import { DashboardPlacement } from '~/types'

export const scene: SceneExport = {
    component: ProjectHomepage,
    logic: projectHomepageLogic,
}

function HomePageContent(): JSX.Element {
    const { dashboardLogicProps, isFirstEventCreateEventModalOpen, shouldShowFirstEventBanner } =
        useValues(projectHomepageLogic)
    const { showInviteModal } = useActions(inviteLogic)
    const { clickFirstEventBannerCTA, closeFirstEventCreateEventModal } = useActions(projectHomepageLogic)
    const { dashboard } = useValues(dashboardLogic(dashboardLogicProps as DashboardLogicProps))
    const [isConfigurePinnedTabsOpen, setIsConfigurePinnedTabsOpen] = useState(false)

    // TODO: Remove this after AA test is over
    const { featureFlags } = useValues(featureFlagLogic)
    const aaTestBayesianLegacy = featureFlags[FEATURE_FLAGS.AA_TEST_BAYESIAN_LEGACY]
    const aaTestBayesianNew = featureFlags[FEATURE_FLAGS.AA_TEST_BAYESIAN_NEW]

    return (
        <SceneContent className="ProjectHomepage">
            {/* TODO: Remove this after AA test is over. Just a hidden element. */}
            <span className="hidden" data-attr="aa-test-flag-result">
                AA test flag result: {String(aaTestBayesianLegacy)} {String(aaTestBayesianNew)}
            </span>

            {shouldShowFirstEventBanner && (
                <div className="my-4" data-attr="first-event-banner">
                    <LemonBanner type="info">
                        <div className="flex flex-col gap-3 @md:flex-row @md:items-center @md:justify-between">
                            <div className="grow">
                                Welcome to PostHog! Create your first event to start tracking user behavior.
                            </div>
                            <div className="flex items-center gap-3 shrink-0">
                                <LemonButton
                                    type="primary"
                                    size="small"
                                    onClick={clickFirstEventBannerCTA}
                                    data-attr="first-event-banner-create-event"
                                >
                                    Create event
                                </LemonButton>
                                <Link
                                    to="https://posthog.com/docs/data/events"
                                    target="_blank"
                                    data-attr="first-event-banner-learn-more"
                                >
                                    Learn more
                                </Link>
                            </div>
                        </div>
                    </LemonBanner>
                </div>
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
                            onClick={() => setIsConfigurePinnedTabsOpen(true)}
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
                        setIsConfigurePinnedTabsOpen(true)
                    }}
                    scene={Scene.ProjectHomepage}
                />
            )}
            <ConfigurePinnedTabsModal
                isOpen={isConfigurePinnedTabsOpen}
                onClose={() => setIsConfigurePinnedTabsOpen(false)}
            />
            <EventDefinitionModal isOpen={isFirstEventCreateEventModalOpen} onClose={closeFirstEventCreateEventModal} />
        </SceneContent>
    )
}

export function ProjectHomepage(): JSX.Element {
    const { dashboardLogicProps } = useValues(projectHomepageLogic)
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
