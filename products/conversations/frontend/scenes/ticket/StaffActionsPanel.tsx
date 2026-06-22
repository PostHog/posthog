import { useValues } from 'kea'

import { LemonCollapse } from '@posthog/lemon-ui'

import { AdminLoginButtons } from '~/layout/navigation/ImpersonationNotice/AdminLoginButtons'
import { impersonationNoticeLogic } from '~/layout/navigation/ImpersonationNotice/impersonationNoticeLogic'

export function StaffActionsPanel(): JSX.Element {
    const { ticketContext, adminLoginUrls } = useValues(impersonationNoticeLogic)

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
                                <AdminLoginButtons ticketContext={ticketContext} adminLoginUrls={adminLoginUrls} />
                            </div>
                        </div>
                    ),
                },
            ]}
        />
    )
}
