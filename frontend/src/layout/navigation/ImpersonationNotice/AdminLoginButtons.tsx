import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { impersonationNoticeLogic } from './impersonationNoticeLogic'

export function AdminLoginButtons(): JSX.Element {
    const { ticketContext, isInitiatingImpersonation, adminViewUrls } = useValues(impersonationNoticeLogic)
    const { initiateImpersonation } = useActions(impersonationNoticeLogic)

    const disabledReason = !ticketContext?.email
        ? 'This ticket has no associated email'
        : ticketContext.identityVerified === false
          ? "This customer's identity could not be verified, so login as is disabled"
          : undefined

    // Region labels only matter when the region is unknown and we offer both.
    const showRegionLabel = adminViewUrls.length > 1

    // Resolving the customer's region and user happens server-side, so a single
    // button suffices — staff are routed to the right region automatically. The side
    // dropdown is the manual fallback (e.g. unverified identity): view the user in
    // the Django admin and log in from there.
    return (
        <div className="flex flex-wrap justify-end gap-2">
            <LemonButton
                type="secondary"
                size="small"
                disabledReason={disabledReason}
                loading={isInitiatingImpersonation}
                onClick={() => initiateImpersonation()}
                sideAction={{
                    dropdown: {
                        placement: 'bottom-end',
                        overlay:
                            adminViewUrls.length > 0 ? (
                                adminViewUrls.map(({ region, url }) => (
                                    <LemonButton key={region} fullWidth size="small" to={url} targetBlank>
                                        View user in Django admin{showRegionLabel ? ` (${region})` : ''}
                                    </LemonButton>
                                ))
                            ) : (
                                <LemonButton
                                    fullWidth
                                    size="small"
                                    disabledReason="This ticket has no associated email"
                                >
                                    View user in Django admin
                                </LemonButton>
                            ),
                    },
                }}
            >
                Login as {ticketContext?.email || 'customer'}
            </LemonButton>
        </div>
    )
}
