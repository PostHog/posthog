import { useValues } from 'kea'

import { LemonButton, LemonCollapse } from '@posthog/lemon-ui'

import { impersonationNoticeLogic } from '~/layout/navigation/ImpersonationNotice/impersonationNoticeLogic'

export function StaffActionsPanel(): JSX.Element {
    const { ticketContext, adminLoginUrl } = useValues(impersonationNoticeLogic)

    const disabledReason = !ticketContext?.email
        ? 'This ticket has no associated email'
        : !ticketContext?.region
          ? 'Unable to determine region for this ticket, no login available'
          : !adminLoginUrl
            ? 'Unable to determine admin URL'
            : undefined

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
                            <div className="flex items-center justify-between">
                                <span className="text-xs text-muted-alt">
                                    {ticketContext?.email ? (
                                        <>
                                            Customer: <span className="text-success">{ticketContext.email}</span>
                                        </>
                                    ) : (
                                        'No customer email on this ticket'
                                    )}
                                </span>
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    tooltip={
                                        !disabledReason
                                            ? 'This currently redirects to the admin login page, but in future will log you in directly.'
                                            : undefined
                                    }
                                    disabledReason={disabledReason}
                                    onClick={() => adminLoginUrl && window.open(adminLoginUrl, '_blank')}
                                >
                                    Login as {ticketContext?.email || 'customer'}
                                </LemonButton>
                            </div>
                        </div>
                    ),
                },
            ]}
        />
    )
}
