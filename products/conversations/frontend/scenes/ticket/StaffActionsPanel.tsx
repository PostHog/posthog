import { useValues } from 'kea'

import { LemonCard, LemonCollapse } from '@posthog/lemon-ui'

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
                        <LemonCard hoverEffect={false} className="flex flex-col gap-2 p-3">
                            <h3 className="text-sm font-semibold">
                                {ticketContext?.email
                                    ? `Login as ${ticketContext.email}`
                                    : 'No customer email on this ticket'}
                            </h3>
                            <AdminLoginButtons
                                ticketContext={ticketContext}
                                adminLoginUrls={adminLoginUrls}
                                useRegionLabels
                            />
                        </LemonCard>
                    ),
                },
            ]}
        />
    )
}
