import { ReactNode } from 'react'

import { TicketSidebarWidgetIcon } from '../TicketSidebarWidgetIcon/TicketSidebarWidgetIcon'
import { TicketSidebarWidgetKey, ticketSidebarWidget } from '../TicketSidebarWidgets/ticketSidebarLayout'

interface TicketSidebarWidgetTitleProps {
    widgetKey: TicketSidebarWidgetKey
    children?: ReactNode
}

export function TicketSidebarWidgetTitle({ widgetKey, children }: TicketSidebarWidgetTitleProps): JSX.Element {
    return (
        <span className="flex items-center gap-1.5 min-w-0">
            <TicketSidebarWidgetIcon widgetKey={widgetKey} />
            <span className="truncate">{ticketSidebarWidget(widgetKey).title}</span>
            {children}
        </span>
    )
}
