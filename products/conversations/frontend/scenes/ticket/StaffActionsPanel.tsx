import { useValues } from 'kea'

import { LemonBanner, LemonCollapse } from '@posthog/lemon-ui'

import { AdminLoginButtons } from '~/layout/navigation/ImpersonationNotice/AdminLoginButtons'
import { impersonationNoticeLogic } from '~/layout/navigation/ImpersonationNotice/impersonationNoticeLogic'

export function StaffActionsPanel(): JSX.Element {
    const { ticketContext } = useValues(impersonationNoticeLogic)

    // Two distinct non-verified states: never checked (null/undefined) allows login with a
    // caution, while an explicit false (intake found no attestation: no widget HMAC, or email
    // failed SPF/alignment) blocks direct login, leaving only the manual admin path.
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
                                    This ticket's identity isn't verified: the message didn't carry a signed identity,
                                    or the email failed sender authentication. The customer email is self-reported, so
                                    verify who you're talking to before logging in as them from the Django admin.
                                </LemonBanner>
                            ) : identityUnknown ? (
                                <LemonBanner type="warning">
                                    This ticket's identity was never checked (not the same as failing verification),
                                    which happens on imported, outbound, and older tickets. Confirm you're logging in as
                                    the right customer before proceeding.
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
