import { IconCheckCircle } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import type { Ticket } from '../../types'

interface TicketEmailDeliveryProps {
    ticket: Pick<Ticket, 'email_delivery' | 'email_from'> | null
}

export function TicketEmailDelivery({ ticket }: TicketEmailDeliveryProps): JSX.Element | null {
    if (!ticket?.email_delivery || !ticket.email_from) {
        return null
    }

    return (
        <div className="flex justify-between items-start gap-2">
            <span className="text-muted-alt shrink-0">Email delivery</span>
            {ticket.email_delivery === 'active' ? (
                <span className="flex items-center justify-end gap-1 min-w-0">
                    <span className="text-xs truncate" title={ticket.email_from}>
                        {ticket.email_from}
                    </span>
                    <Tooltip title="Email confirmed. The customer replied to the confirmation email from this address. Replies on this ticket are emailed to it. In the widget, they show only to a customer who is logged in with this address.">
                        <span className="text-success text-base shrink-0 flex" aria-label="Email confirmed">
                            <IconCheckCircle />
                        </span>
                    </Tooltip>
                </span>
            ) : (
                <span
                    className="text-xs truncate text-right"
                    title={`A confirmation email was sent to ${ticket.email_from}. Replies are emailed after the customer replies to it.`}
                >
                    Waiting for confirmation
                </span>
            )}
        </div>
    )
}
