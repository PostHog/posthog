import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { impersonationNoticeLogic } from './impersonationNoticeLogic'

export function AdminLoginButtons(): JSX.Element {
    const { ticketContext, isInitiatingImpersonation } = useValues(impersonationNoticeLogic)
    const { initiateImpersonation } = useActions(impersonationNoticeLogic)

    const disabledReason = !ticketContext?.email
        ? 'This ticket has no associated email'
        : ticketContext.identityVerified === false
          ? "This customer's identity could not be verified, so login as is disabled"
          : undefined

    // Resolving the customer's region and user happens server-side, so a single
    // button suffices — staff are routed to the right region automatically.
    return (
        <div className="flex flex-wrap justify-end gap-2">
            <LemonButton
                type="secondary"
                size="small"
                disabledReason={disabledReason}
                loading={isInitiatingImpersonation}
                onClick={() => initiateImpersonation()}
            >
                Login as {ticketContext?.email || 'customer'}
            </LemonButton>
        </div>
    )
}
