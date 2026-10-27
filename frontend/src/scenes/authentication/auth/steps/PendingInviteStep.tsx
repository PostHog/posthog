import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { AuthBanner } from 'scenes/authentication/shared/authScene/AuthBanner'
import { AuthCardTitle } from 'scenes/authentication/shared/authScene/AuthCardTitle'
import { AuthSceneCard } from 'scenes/authentication/shared/authScene/AuthScene'

import { UseDifferentEmailLink } from '../components/UseDifferentEmailLink'
import { signupLogic } from '../signupLogic'

export function PendingInviteStep(): JSX.Element {
    const { signupEmail, pendingInvite, pendingInviteResent, isPendingInviteResending } = useValues(signupLogic)
    const { resendPendingInvite, dismissPendingInvite } = useActions(signupLogic)
    const org = pendingInvite?.organization_name ?? 'your team'

    return (
        <AuthSceneCard footer={<UseDifferentEmailLink />} showPendingConnection>
            <AuthCardTitle
                title="You've already been invited"
                sub={
                    <span>
                        <b className="text-primary">{org}</b> <span>invited</span>{' '}
                        <span className="AuthScene__mono">{signupEmail}</span>{' '}
                        <span>to join them on PostHog. The invite link is in your inbox.</span>
                    </span>
                }
                className="mb-5"
            />
            {pendingInviteResent ? (
                <AuthBanner variant="success">
                    {`Sent. Look for an email from ${org}. The link inside takes you straight in.`}
                </AuthBanner>
            ) : (
                <div className="flex flex-col gap-2.5">
                    <LemonButton
                        type="primary"
                        size="large"
                        center
                        fullWidth
                        data-attr="pending-invite-resend"
                        loading={isPendingInviteResending}
                        onClick={() => resendPendingInvite(signupEmail)}
                    >
                        Resend invite email
                    </LemonButton>
                    <LemonButton
                        size="large"
                        center
                        fullWidth
                        data-attr="pending-invite-create-own-org"
                        onClick={() => dismissPendingInvite()}
                    >
                        I'd rather create my own organization
                    </LemonButton>
                </div>
            )}
        </AuthSceneCard>
    )
}
