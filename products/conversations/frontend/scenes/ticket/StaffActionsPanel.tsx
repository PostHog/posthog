import { useValues } from 'kea'

import { LemonBanner, LemonCollapse } from '@posthog/lemon-ui'

import { AdminLoginButtons } from '~/layout/navigation/ImpersonationNotice/AdminLoginButtons'
import { impersonationNoticeLogic } from '~/layout/navigation/ImpersonationNotice/impersonationNoticeLogic'

export function StaffActionsPanel(): JSX.Element {
    const { ticketContext } = useValues(impersonationNoticeLogic)

    // Two distinct non-verified states: never checked (null/undefined) allows login with
    // a caution, while an explicit false means the sender claimed this email but failed
    // verification — direct login is blocked, only the manual admin path remains.
    const identityUnknown = !!ticketContext?.email && ticketContext.identityVerified == null
    const identityFailed = !!ticketContext?.email && ticketContext.identityVerified === false

    const emailClassName = identityFailed ? 'text-danger' : identityUnknown ? 'text-warning' : 'text-success'

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
                            {identityFailed ? (
                                <LemonBanner type="error">
                                    This ticket failed identity verification: the sender claimed this email but couldn't
                                    prove they own it, so logging in directly is disabled. "View user in Django admin"
                                    looks up the claimed email, so verify the customer's identity before logging in as
                                    them from there.
                                </LemonBanner>
                            ) : identityUnknown ? (
                                <LemonBanner type="warning">
                                    This ticket's identity was never checked (not the same as failed verification).
                                    Confirm you're logging in as the right customer before proceeding.
                                </LemonBanner>
                            ) : null}
                            <div className="flex items-center justify-between gap-2">
                                <span className="text-xs text-muted-alt">
                                    {ticketContext?.email ? (
                                        <>
                                            Customer: <span className={emailClassName}>{ticketContext.email}</span>
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
