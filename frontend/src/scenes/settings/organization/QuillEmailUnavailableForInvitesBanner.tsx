import { Button, Item, ItemContent, ItemDescription } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

export function QuillEmailUnavailableForInvitesBanner(): JSX.Element {
    return (
        <Item tone="info" size="sm" className="w-full">
            <ItemContent>
                <ItemDescription>
                    This PostHog instance isn't{' '}
                    <Button
                        variant="link"
                        size="inline"
                        nativeButton={false}
                        render={
                            <LinkPrimitive to="https://posthog.com/docs/self-host/configure/email" target="_blank" />
                        }
                    >
                        configured to send emails
                    </Button>
                    . Remember to <u>share the invite link</u> with each team member you invite.
                </ItemDescription>
            </ItemContent>
        </Item>
    )
}
