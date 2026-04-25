import { IconLetter } from '@posthog/icons'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { Link } from 'lib/lemon-ui/Link'

const ORG_MEMBERSHIP_DOCS_URL =
    'https://posthog.com/docs/settings/organizations?utm_medium=in-product&utm_campaign=signup-join-existing-org'

function openJoinExistingOrgDialog(): void {
    LemonDialog.open({
        width: 480,
        content: (
            <div className="flex flex-col items-center text-center px-2 pt-2 pb-4">
                <div className="flex items-center justify-center w-14 h-14 rounded-full bg-accent-highlight-secondary mb-4">
                    <IconLetter className="text-2xl text-accent" />
                </div>
                <h2 className="text-xl font-bold mb-2">You'll need your invite link to join</h2>
                <p className="text-secondary mb-3">
                    Joining an existing PostHog organization happens through a personal invite link emailed to you —
                    not from this signup page. Here's how to get in:
                </p>
                <ol className="text-secondary text-sm text-left mb-3 pl-5 list-decimal deprecated-space-y-1">
                    <li>Search your inbox (and spam folder) for an email from PostHog with your invite link.</li>
                    <li>
                        If you can't find one, ask a teammate who's already in the organization to resend it from{' '}
                        <span className="font-semibold">Settings → Members</span>.
                    </li>
                    <li>Open the invite email and click the link to finish joining.</li>
                </ol>
                <p className="text-secondary text-sm mb-0">
                    Need more detail?{' '}
                    <Link
                        to={ORG_MEMBERSHIP_DOCS_URL}
                        target="_blank"
                        targetBlankIcon
                        data-attr="signup-join-existing-org-docs"
                    >
                        Read about organization membership
                    </Link>
                    .
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
            <Link
                onClick={openJoinExistingOrgDialog}
                data-attr="signup-join-existing-org"
                className="text-secondary hover:underline focus-visible:underline"
                aria-haspopup="dialog"
            >
                Joining a team? See how to use your invite →
            </Link>
        </div>
    )
}
