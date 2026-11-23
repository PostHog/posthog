import { Button } from '@posthog/quill'

import { QuillEmailUnavailableForInvitesBanner } from './QuillEmailUnavailableForInvitesBanner'
import { QuillInvitesTable } from './QuillInvitesTable'

export function QuillInvites({
    emailServiceAvailable,
    onInvite,
    inviteDisabledReason,
}: {
    emailServiceAvailable: boolean
    onInvite: () => void
    inviteDisabledReason?: string
}): JSX.Element {
    return (
        <div className="flex flex-col items-start gap-4">
            {!emailServiceAvailable && <QuillEmailUnavailableForInvitesBanner />}
            <div className="w-full">
                <QuillInvitesTable />
            </div>
            <Button
                variant="primary"
                onClick={onInvite}
                data-attr="invite-teammate-button"
                disabledReason={inviteDisabledReason}
            >
                Invite team member
            </Button>
        </div>
    )
}
