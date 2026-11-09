import { useActions, useValues } from 'kea'

import { LemonButton, LemonCollapse } from '@posthog/lemon-ui'

import { AdminLoginButtons } from '~/layout/navigation/ImpersonationNotice/AdminLoginButtons'
import { impersonationNoticeLogic } from '~/layout/navigation/ImpersonationNotice/impersonationNoticeLogic'

import { supportTicketSceneLogic } from './supportTicketSceneLogic'

export function StaffActionsPanel(): JSX.Element {
    const { ticketContext, adminLoginUrls } = useValues(impersonationNoticeLogic)
    const { ticket, ticketBriefWriting } = useValues(supportTicketSceneLogic)
    const { writeTicketBrief } = useActions(supportTicketSceneLogic)

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
                            <div className="flex flex-col gap-2">
                                <span className="text-xs text-muted-alt break-all">
                                    {ticketContext?.email ? (
                                        <>
                                            Customer:{' '}
                                            <span
                                                className={ticketContext.isEmailUnverified ? undefined : 'text-success'}
                                            >
                                                {ticketContext.email}
                                            </span>
                                            {ticketContext.isEmailUnverified && ' (not verified)'}
                                        </>
                                    ) : (
                                        'No customer email on this ticket'
                                    )}
                                </span>
                                <AdminLoginButtons ticketContext={ticketContext} adminLoginUrls={adminLoginUrls} />
                            </div>
                            <LemonButton
                                type="secondary"
                                size="small"
                                fullWidth
                                center
                                data-attr="ticket-write-brief"
                                loading={ticketBriefWriting}
                                disabledReason={ticket ? undefined : 'Still loading the ticket'}
                                onClick={() => writeTicketBrief()}
                            >
                                {ticket?.ticket_brief ? 'Write the brief again' : 'Write the brief'}
                            </LemonButton>
                        </div>
                    ),
                },
            ]}
        />
    )
}
