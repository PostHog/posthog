import { LemonCollapse } from '@posthog/lemon-ui'

import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'

import { ActivityScope } from '~/types'

interface TicketActivityPanelProps {
    ticketId: string
}

export function TicketActivityPanel({ ticketId }: TicketActivityPanelProps): JSX.Element {
    return (
        <LemonCollapse
            className="bg-surface-primary"
            panels={[
                {
                    key: 'ticket-activity',
                    header: 'Ticket activity history',
                    content: (
                        <div className="max-h-96 overflow-auto">
                            <ActivityLog scope={ActivityScope.TICKET} id={ticketId} />
                        </div>
                    ),
                },
            ]}
        />
    )
}
