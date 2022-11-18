import { useActions, useValues } from 'kea'
import { ingestionLogicV2 } from 'scenes/ingestion/v2/ingestionLogic'
import { LemonButton } from 'lib/components/LemonButton'
import './Panels.scss'
import { LemonDivider } from 'lib/components/LemonDivider'
import { IconChevronRight } from 'lib/components/icons'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { GENERATING_DEMO_DATA } from '../constants'
import { teamLogic } from 'scenes/teamLogic'
import { organizationLogic } from 'scenes/organizationLogic'

export function TeamInvitedPanel(): JSX.Element {
    const { completeOnboarding, next } = useActions(ingestionLogicV2)
    const { createTeam } = useActions(teamLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const {
        reportIngestionContinueWithoutVerifying,
        reportIngestionTryWithDemoDataClicked,
        reportProjectCreationSubmitted,
    } = useActions(eventUsageLogic)

    const demoTeamName: string = 'Demo'

    return (
        <div>
            <h1 className="ingestion-title">Help is on the way!</h1>
            <p className="prompt-text">
                You can still explore all PostHog has to offer while you wait for your team members to join.
            </p>
            <LemonDivider thick dashed className="my-6" />
            <div className="flex flex-col mb-6">
                <LemonButton
                    onClick={() => {
                        reportIngestionTryWithDemoDataClicked()
                        next({ isTechnicalUser: false, platform: GENERATING_DEMO_DATA })
                        createTeam({ name: demoTeamName, is_demo: true })
                        next({ isTechnicalUser: false, platform: GENERATING_DEMO_DATA })
                        reportProjectCreationSubmitted(
                            currentOrganization?.teams ? currentOrganization.teams.length : 0,
                            demoTeamName.length
                        )
                    }}
                    fullWidth
                    size="large"
                    className="mb-4"
                    type="primary"
                    sideIcon={<IconChevronRight />}
                >
                    <div className="mt-4 mb-0">
                        <p className="mb-2">Quickly try PostHog with some demo data.</p>
                        <p className="font-normal text-xs">
                            Explore insights, create dashboards, try out cohorts, and more.
                        </p>
                    </div>
                </LemonButton>
                <LemonButton
                    onClick={() => {
                        completeOnboarding()
                        reportIngestionContinueWithoutVerifying()
                    }}
                    fullWidth
                    size="large"
                    className="mb-4"
                    type="secondary"
                    sideIcon={<IconChevronRight />}
                >
                    <div className="mt-4 mb-0">
                        <p className="mb-2">Continue without any events.</p>
                        <p className="font-normal text-xs">
                            It might look a little empty in there, but we'll do our best.
                        </p>
                    </div>
                </LemonButton>
            </div>
        </div>
    )
}
