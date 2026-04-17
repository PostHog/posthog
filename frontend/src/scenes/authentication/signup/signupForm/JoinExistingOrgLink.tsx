import { IconLetter } from '@posthog/icons'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { Link } from 'lib/lemon-ui/Link'

function openJoinExistingOrgDialog(): void {
    LemonDialog.open({
        title: '',
        width: 480,
        description: (
            <div className="flex flex-col items-center text-center px-2 pb-2">
                <div className="flex items-center justify-center w-14 h-14 rounded-full bg-accent-highlight-secondary mb-4">
                    <IconLetter className="text-2xl text-accent" />
                </div>
                <h2 className="text-xl font-bold mb-2">Check your email for your invite</h2>
                <p className="text-secondary mb-2">
                    Organization invitations only work by opening the link sent to your email. Signing up here will
                    create a new, separate organization instead of joining the one you were invited to.
                </p>
                <p className="text-secondary text-sm mb-0">
                    Can't find it? Check your spam folder, or ask an admin to resend the invite.
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
                Joining via an invite link?
            </Link>
        </div>
    )
}
