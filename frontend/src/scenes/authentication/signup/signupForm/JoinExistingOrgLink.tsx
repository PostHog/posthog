import { IconLetter } from '@posthog/icons'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { Link } from 'lib/lemon-ui/Link'

function openJoinExistingOrgDialog(): void {
    LemonDialog.open({
        width: 480,
        content: (
            <div className="flex flex-col items-center text-center px-2 pt-2 pb-4">
                <div className="flex items-center justify-center w-14 h-14 rounded-full bg-accent-highlight-secondary mb-4">
                    <IconLetter className="text-2xl text-accent" />
                </div>
                <h2 className="text-xl font-bold mb-2">You'll need your invite link to join</h2>
                <p className="text-secondary mb-2">
                    When a teammate invites you to a PostHog organization, we email you a personal invite link. You can
                    only join the existing organization by opening that email and clicking the link.
                </p>
                <p className="text-secondary text-sm mb-0">
                    Didn't get an email? Check your spam folder, or ask the teammate who invited you to resend it from
                    the organization's members settings.
                </p>
            </div>
        ),
        primaryButton: {
            children: 'Got it',
            type: 'primary',
        },
    })
}

export function JoinExistingOrgLink(): JSX.Element {
    return (
        <div className="text-center mt-3 text-xs">
            <Link onClick={openJoinExistingOrgDialog} data-attr="signup-join-existing-org" className="text-secondary">
                Trying to join an existing organization?
            </Link>
        </div>
    )
}
