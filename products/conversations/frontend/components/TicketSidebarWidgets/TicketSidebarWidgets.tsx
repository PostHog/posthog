import { useActions, useValues } from 'kea'
import { Fragment } from 'react'

import { IconPencil } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TicketSidebarWidgetsEditor } from '../TicketSidebarWidgetsEditor/TicketSidebarWidgetsEditor'
import { TicketSidebarWidgetSlots } from './ticketSidebarLayout'
import { ticketSidebarWidgetsLogic } from './ticketSidebarWidgetsLogic'

export function TicketSidebarWidgets({ slots }: { slots: TicketSidebarWidgetSlots }): JSX.Element {
    const { layout, isEditing } = useValues(ticketSidebarWidgetsLogic)
    const { startEditing } = useActions(ticketSidebarWidgetsLogic)

    if (isEditing) {
        return <TicketSidebarWidgetsEditor slots={slots} />
    }

    const shown = layout.visible.flatMap((key) => {
        const content = slots[key]?.content
        return content ? [{ key, content }] : []
    })

    return (
        <>
            <div className="flex items-center justify-between gap-2">
                <h3 className="text-sm font-semibold m-0">Widgets</h3>
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    icon={<IconPencil />}
                    onClick={startEditing}
                    data-attr="ticket-sidebar-widgets-edit"
                >
                    Edit widgets
                </LemonButton>
            </div>
            {shown.length === 0 ? (
                <div className="text-xs text-secondary">No widgets to show on this ticket.</div>
            ) : (
                shown.map(({ key, content }) => <Fragment key={key}>{content}</Fragment>)
            )}
        </>
    )
}
