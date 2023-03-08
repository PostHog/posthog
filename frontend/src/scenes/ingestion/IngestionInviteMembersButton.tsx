import { LemonButton } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { IconArrowRight } from 'lib/lemon-ui/icons'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { inviteLogic } from 'scenes/organization/Settings/inviteLogic'

export function IngestionInviteMembersButton(): JSX.Element {
    const { showInviteModal } = useActions(inviteLogic)
    const { reportInviteMembersButtonClicked } = useActions(eventUsageLogic)

    return (
        <LemonButton
            fullWidth
            center
            size="large"
            sideIcon={<IconArrowRight />}
            className="mt-6"
            onClick={() => {
                showInviteModal()
                reportInviteMembersButtonClicked()
            }}
        >
            Invite a team member to help with this step
        </LemonButton>
    )
}
