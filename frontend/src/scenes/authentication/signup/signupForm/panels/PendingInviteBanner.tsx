import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { PendingInvite } from '../signupLogic'

export interface PendingInviteBannerProps {
    invite: PendingInvite
    email: string
    onResend: (email: string) => void
    onDismiss: () => void
    isResending: boolean
    wasResent: boolean
}

export function PendingInviteBanner({
    invite,
    email,
    onResend,
    onDismiss,
    isResending,
    wasResent,
}: PendingInviteBannerProps): JSX.Element {
    return (
        <div className="deprecated-space-y-4 Signup__panel__pending-invite">
            <h2 className="m-0">You've already been invited to PostHog</h2>
            <p className="text-secondary mb-0">
                <b>{invite.organization_name}</b> sent you an invite to join them on PostHog. Look for it in your inbox,
                or have us resend it.
            </p>
            {wasResent ? (
                <LemonBanner type="success">
                    Sent. Check your inbox for the invite link from {invite.organization_name}.
                </LemonBanner>
            ) : (
                <>
                    <LemonButton
                        type="primary"
                        status="alt"
                        fullWidth
                        center
                        size="large"
                        onClick={() => onResend(email)}
                        loading={isResending}
                        disabled={isResending}
                        data-attr="pending-invite-resend"
                    >
                        Resend invite email
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        fullWidth
                        center
                        onClick={onDismiss}
                        data-attr="pending-invite-create-own-org"
                    >
                        I'd like to create my own organization
                    </LemonButton>
                </>
            )}
        </div>
    )
}
