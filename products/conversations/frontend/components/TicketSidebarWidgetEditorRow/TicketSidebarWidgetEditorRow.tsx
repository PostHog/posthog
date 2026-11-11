import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'

import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { SortableDragIcon } from 'lib/lemon-ui/icons'

import { TicketSidebarWidgetKey, ticketSidebarWidget } from '../TicketSidebarWidgets/ticketSidebarLayout'

interface TicketSidebarWidgetEditorRowProps {
    widgetKey: TicketSidebarWidgetKey
    unavailableReason?: string
    onHide: () => void
}

export function TicketSidebarWidgetEditorRow({
    widgetKey,
    unavailableReason,
    onHide,
}: TicketSidebarWidgetEditorRowProps): JSX.Element {
    const { setNodeRef, attributes, listeners, transform, transition } = useSortable({ id: widgetKey })
    const { title, description } = ticketSidebarWidget(widgetKey)

    return (
        <div
            ref={setNodeRef}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ transform: CSS.Transform.toString(transform), transition }}
            className="flex items-start gap-2 rounded border bg-surface-primary p-2"
            data-attr={`ticket-sidebar-widget-row-${widgetKey}`}
        >
            <span
                {...attributes}
                {...listeners}
                aria-label={`Move ${title}`}
                className="cursor-grab text-secondary pt-0.5 shrink-0"
            >
                <SortableDragIcon />
            </span>
            <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold truncate">{title}</div>
                <div className="text-xs text-secondary">{description}</div>
                {unavailableReason && <div className="text-xs text-muted-alt mt-1">{unavailableReason}</div>}
            </div>
            <LemonButton
                size="xsmall"
                icon={<IconX />}
                onClick={onHide}
                tooltip={`Hide ${title}`}
                data-attr="ticket-sidebar-widget-hide"
            />
        </div>
    )
}
