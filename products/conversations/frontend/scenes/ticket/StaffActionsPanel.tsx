import { useValues } from 'kea'

import { LemonButton, LemonCollapse } from '@posthog/lemon-ui'

import { impersonationNoticeLogic } from '~/layout/navigation/ImpersonationNotice/impersonationNoticeLogic'

export function StaffActionsPanel(): JSX.Element {
    const { ticketContext, adminLoginUrls } = useValues(impersonationNoticeLogic)

    const disabledReason = !ticketContext?.email
        ? 'This ticket has no associated email'
        : adminLoginUrls.length === 0
          ? 'Unable to determine admin URL'
          : undefined

    // Region is ambiguous when we couldn't infer it, so we offer one button per
    // region and label each so staff know which admin page they're opening.
    const showRegionLabel = adminLoginUrls.length > 1

    return (
        <LemonCollapse
            className="bg-surface-primary"
            defaultActiveKey="staff-actions"
            panels={[
                {
                    key: 'staff-actions',
                    header: 'Staff actions',
                    content: (
                        <div className="space-y-2">
                            <div className="flex items-center justify-between gap-2">
                                <span className="text-xs text-muted-alt">
                                    {ticketContext?.email ? (
                                        <>
                                            Customer: <span className="text-success">{ticketContext.email}</span>
                                        </>
                                    ) : (
                                        'No customer email on this ticket'
                                    )}
                                </span>
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
                                                Login as {ticketContext?.email}
                                                {showRegionLabel ? ` (${region})` : ''}
                                            </LemonButton>
                                        ))
                                    )}
                                </div>
                            </div>
                        </div>
                    ),
                },
            ]}
        />
    )
}
