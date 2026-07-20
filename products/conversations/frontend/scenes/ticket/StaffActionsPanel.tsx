import { useValues } from 'kea'

import { LemonBanner, LemonCollapse } from '@posthog/lemon-ui'

import { AdminLoginButtons } from '~/layout/navigation/ImpersonationNotice/AdminLoginButtons'
import { impersonationNoticeLogic } from '~/layout/navigation/ImpersonationNotice/impersonationNoticeLogic'

export function StaffActionsPanel(): JSX.Element {
    const { ticketContext } = useValues(impersonationNoticeLogic)

    // null/undefined means the identity signal was never assessed for this ticket —
    // login as is still allowed, but warn staff to confirm they have the right customer.
    const identityUnknown = !!ticketContext?.email && ticketContext.identityVerified == null

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
                            {identityUnknown && (
                                <LemonBanner type="warning">
                                    This ticket's identity hasn't been verified. Confirm you're logging in as the right
                                    customer before proceeding.
                                </LemonBanner>
                            )}
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
                                <AdminLoginButtons />
                            </div>
                        </div>
                    ),
                },
            ]}
        />
    )
}
