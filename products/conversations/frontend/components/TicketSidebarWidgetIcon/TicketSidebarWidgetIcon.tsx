import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { TicketSidebarWidgetKey, ticketSidebarWidget } from '../TicketSidebarWidgets/ticketSidebarLayout'

export function TicketSidebarWidgetIcon({ widgetKey }: { widgetKey: TicketSidebarWidgetKey }): JSX.Element {
    return (
        <span className="flex size-4 shrink-0 items-center justify-center group/colorful-product-icons colorful-product-icons-true [&_svg]:size-4">
            {iconForType(ticketSidebarWidget(widgetKey).iconType)}
        </span>
    )
}
