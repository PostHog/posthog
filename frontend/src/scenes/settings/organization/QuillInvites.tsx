import { Button, Item, ItemContent, ItemDescription } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

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
            {!emailServiceAvailable && (
                <Item tone="info" size="sm" className="w-full">
                    <ItemContent>
                        <ItemDescription>
                            This PostHog instance isn't{' '}
                            <Button
                                variant="link"
                                size="inline"
                                nativeButton={false}
                                render={
                                    <LinkPrimitive
                                        to="https://posthog.com/docs/self-host/configure/email"
                                        target="_blank"
                                    />
                                }
                            >
                                configured to send emails
                            </Button>
                            . Remember to <u>share the invite link</u> with each team member you invite.
                        </ItemDescription>
                    </ItemContent>
                </Item>
            )}
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
