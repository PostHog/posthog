import { useActions } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonButtonPropsBase } from '@posthog/lemon-ui'

import { inviteLogic } from 'lib/logic/inviteLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

export function InviteMembersButton({
    text = 'Invite members',
    center = false,
    type = 'tertiary',
    ...props
}: LemonButtonPropsBase & { text?: string }): JSX.Element {
    const { showInviteModal } = useActions(inviteLogic)
    const { reportInviteMembersButtonClicked } = useActions(eventUsageLogic)

    return (
        <LemonButton
            icon={<IconPlusSmall />}
            onClick={() => {
                showInviteModal()
                reportInviteMembersButtonClicked()
            }}
            center={center}
            type={type}
            fullWidth
            data-attr="top-menu-invite-team-members"
            {...props}
        >
            {text}
        </LemonButton>
    )
}
