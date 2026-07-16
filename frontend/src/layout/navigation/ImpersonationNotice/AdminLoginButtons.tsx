import { LemonButton } from '@posthog/lemon-ui'

import { AdminLoginUrl, ImpersonationTicketContext } from './impersonationNoticeLogic'

export function AdminLoginButtons({
    ticketContext,
    adminLoginUrls,
    useRegionLabels = false,
}: {
    ticketContext: ImpersonationTicketContext | null
    adminLoginUrls: AdminLoginUrl[]
    useRegionLabels?: boolean
}): JSX.Element {
    const email = ticketContext?.email

    // Region is ambiguous when we couldn't infer it, so we offer one button per
    // region and label each so staff know which admin page they're opening.
    const showRegionLabel = adminLoginUrls.length > 1

    return (
        <div className="flex flex-wrap justify-end gap-2">
            {!email ? (
                <LemonButton
                    type="secondary"
                    size="small"
                    disabledReason="This ticket has no associated email"
                >
                    {useRegionLabels ? 'Login' : 'Login as customer'}
                </LemonButton>
            ) : (
                adminLoginUrls.map(({ region, url }) => (
                    <LemonButton
                        key={region}
                        type="secondary"
                        size="small"
                        tooltip={`Login as ${email} on ${region}. This currently redirects to the admin login page, but in future will log you in directly.`}
                        onClick={() => window.open(url, '_blank')}
                    >
                        {useRegionLabels
                            ? `${region} region`
                            : `Login as ${email}${showRegionLabel ? ` (${region})` : ''}`}
                    </LemonButton>
                ))
            )}
        </div>
    )
}
