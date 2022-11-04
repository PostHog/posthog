import { useActions } from 'kea'
import { ingestionLogic } from 'scenes/ingestion/v2/ingestionLogic'
import { LemonButton } from 'lib/components/LemonButton'
import './Panels.scss'
import { LemonDivider } from 'lib/components/LemonDivider'
import { IconChevronRight } from 'lib/components/icons'
import { inviteLogic } from 'scenes/organization/Settings/inviteLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

export function InviteTeamPanel(): JSX.Element {
    const { setTechnical } = useActions(ingestionLogic)
    const { showInviteModal } = useActions(inviteLogic)
    const { reportInviteMembersButtonClicked } = useActions(eventUsageLogic)

    return (
        <div>
            <h1 className="ingestion-title">Welcome to PostHog</h1>
            <p>
                PostHog collects events from your website, mobile apps, backend, and more. To get started, we'll need to
                add a code snippet to your product.
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
            </div>
        </div>
    )
}
