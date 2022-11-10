import { useActions } from 'kea'
import { ingestionLogic } from 'scenes/ingestion/v2/ingestionLogic'
import { LemonButton } from 'lib/components/LemonButton'
import './Panels.scss'
import { LemonDivider } from 'lib/components/LemonDivider'
import { IconArrowRight, IconChevronRight } from 'lib/components/icons'
import { inviteLogic } from 'scenes/organization/Settings/inviteLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { BOOKMARKLET } from '../constants'

export function InviteTeamPanel(): JSX.Element {
    const { setTechnical, setPlatform } = useActions(ingestionLogic)
    const { showInviteModal } = useActions(inviteLogic)
    const { reportInviteMembersButtonClicked } = useActions(eventUsageLogic)

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
                    onClick={() => setTechnical(true)}
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
                        setTechnical(false)
                        showInviteModal()
                        reportInviteMembersButtonClicked()
                    }}
                    fullWidth
                    size="large"
                    className="mb-4"
                    type="secondary"
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
                        setTechnical(false)
                        setPlatform(BOOKMARKLET)
                    }}
                    center
                    fullWidth
                    size="large"
                    type="tertiary"
                    sideIcon={<IconArrowRight />}
                >
                    I'm just exploring
                </LemonButton>
            </div>
        </div>
    )
}
