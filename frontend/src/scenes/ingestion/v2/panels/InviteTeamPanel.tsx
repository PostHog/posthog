import { useActions, useValues } from 'kea'
import { ingestionLogicV2 } from 'scenes/ingestion/v2/ingestionLogic'
import { LemonButton } from 'lib/components/LemonButton'
import './Panels.scss'
import { LemonDivider } from 'lib/components/LemonDivider'
import { IconChevronRight } from 'lib/components/icons'
import { inviteLogic } from 'scenes/organization/Settings/inviteLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'

export function InviteTeamPanel(): JSX.Element {
    const { next } = useActions(ingestionLogicV2)
    const { showInviteModal } = useActions(inviteLogic)
    const { reportInviteMembersButtonClicked, reportProjectCreationSubmitted } = useActions(eventUsageLogic)
    const { createTeam } = useActions(teamLogic)
    const { currentOrganization } = useValues(organizationLogic)

    const demoTeamName: string = 'Demo'

    return (
        <div>
            <h1 className="ingestion-title">Welcome to PostHog</h1>
            <p className="prompt-text">
                PostHog enables you to <b>understand your customers, answer product questions, and test new features</b>{' '}
                - all in our comprehensive product suite. To get started, we'll need to add a code snippet to your
                product.
            </p>
            <LemonDivider thick dashed className="my-6" />
            <div className="flex flex-col mb-6">
                <LemonButton
                    onClick={() => next({ isTechnicalUser: true })}
                    fullWidth
                    size="large"
                    className="mb-4"
                    type="primary"
                    sideIcon={<IconChevronRight />}
                >
                    <div className="mt-4 mb-0">
                        <p className="mb-2">I can add a code snippet to my product.</p>
                        <p className="font-normal text-xs">
                            Available for JavaScript, Android, iOS, React Native, Node.js, Ruby, Go, and more.
                        </p>
                    </div>
                </LemonButton>
                <LemonButton
                    onClick={() => {
                        showInviteModal()
                        reportInviteMembersButtonClicked()
                    }}
                    fullWidth
                    size="large"
                    className="mb-4"
                    type="primary"
                    sideIcon={<IconChevronRight />}
                >
                    <div className="mt-4 mb-0">
                        <p className="mb-2">I'll need a team member to add the code snippet to our product.</p>
                        <p className="font-normal text-xs">
                            We'll send an invite and instructions for getting the code snippet added.
                        </p>
                    </div>
                </LemonButton>
                <LemonButton
                    onClick={() => {
                        createTeam({ name: demoTeamName, is_demo: true })
                        reportProjectCreationSubmitted(
                            currentOrganization?.teams ? currentOrganization.teams.length : 0,
                            demoTeamName.length
                        )
                    }}
                    fullWidth
                    size="large"
                    type="primary"
                    sideIcon={<IconChevronRight />}
                >
                    <div className="mt-4 mb-0">
                        <p className="mb-2">I just want to try PostHog with some demo data.</p>
                        <p className="font-normal text-xs">
                            Explore insights, create dashboards, try out cohorts, and more.
                        </p>
                    </div>
                </LemonButton>
            </div>
        </div>
    )
}
