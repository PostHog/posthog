import { LemonCollapse } from '@posthog/lemon-ui'

import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'

import { ActivityScope } from '~/types'

import { TicketSidebarWidgetTitle } from '../../components/TicketSidebarWidgetTitle/TicketSidebarWidgetTitle'

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
                    header: <TicketSidebarWidgetTitle widgetKey="activity" />,
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
