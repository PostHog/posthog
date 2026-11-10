import { LemonButton } from '@posthog/lemon-ui'

import { AdminLoginUrl, ImpersonationTicketContext } from './impersonationNoticeLogic'

export function AdminLoginButtons({
    ticketContext,
    adminLoginUrls,
}: {
    ticketContext: ImpersonationTicketContext | null
    adminLoginUrls: AdminLoginUrl[]
}): JSX.Element {
    const disabledReason = adminLoginUrls.length === 0 ? 'This ticket has no associated email' : undefined
    const loginTarget =
        ticketContext?.verifiedDistinctId && ticketContext.isEmailUnverified ? 'verified account' : ticketContext?.email

    // Region is ambiguous when we couldn't infer it, so we offer one button per
    // region and label each so staff know which admin page they're opening.
    const showRegionLabel = adminLoginUrls.length > 1

    return (
        <div className="flex flex-wrap justify-end gap-2">
            {disabledReason ? (
                <LemonButton type="secondary" size="small" disabledReason={disabledReason}>
                    Login as {ticketContext?.email || 'customer'}
                </LemonButton>
            ) : (
                adminLoginUrls.map(({ region, url }) => (
                    <LemonButton
                        key={region}
                        type="secondary"
                        size="small"
                        tooltip="This currently redirects to the admin login page, but in future will log you in directly."
                        onClick={() => window.open(url, '_blank')}
                    >
                        Login as {loginTarget}
                        {showRegionLabel ? ` (${region})` : ''}
                    </LemonButton>
                ))
            )}
        </div>
    )
}
