import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import { OrganizationInviteType } from '~/types'

export function cancelInvite(
    invite: OrganizationInviteType,
    deleteInvite: (invite: OrganizationInviteType) => void
): void {
    if (invite.is_expired) {
        deleteInvite(invite)
        return
    }

    LemonDialog.open({
        title: 'Cancel invite',
        description: `Do you want to cancel the invite for ${invite.target_email}?`,
        primaryButton: {
            children: 'Yes, cancel invite',
            status: 'danger',
            onClick: () => deleteInvite(invite),
        },
        secondaryButton: {
            children: 'No, keep invite',
        },
    })
}
