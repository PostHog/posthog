import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { Link } from 'lib/lemon-ui/Link'

function openJoinExistingOrgDialog(): void {
    LemonDialog.open({
        title: 'Joining an existing organization?',
        description: (
            <div className="deprecated-space-y-2">
                <p>
                    To join an organization you've been invited to, open the invitation email from PostHog and click the
                    link inside. That link is the only way to attach your new account to the existing organization.
                </p>
                <p>
                    If you sign up here without using the invite link, you'll create a brand new, separate organization
                    instead of joining the one you were invited to.
                </p>
                <p>
                    Can't find the email? Check your spam folder, or ask an admin of the organization to resend the
                    invite.
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
        <div className="text-center mt-2">
            Been invited to an organization?{' '}
            <Link onClick={openJoinExistingOrgDialog} data-attr="signup-join-existing-org" className="font-bold">
                Use your invite link
            </Link>
        </div>
    )
}
