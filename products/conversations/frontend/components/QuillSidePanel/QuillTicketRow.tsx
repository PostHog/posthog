import { Badge, Item, ItemActions, ItemContent, ItemDescription, ItemTitle, cn } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { stripMarkdown } from 'lib/utils/markdown'

import { type ConversationTicket, sidePanelTicketFilterLabels } from '../../types'
import { ticketStatusBadgeVariant } from './ticketStatusBadgeVariant'

export function QuillTicketRow({ ticket, onOpen }: { ticket: ConversationTicket; onOpen: () => void }): JSX.Element {
    const unread = ticket.unread_count ?? 0
    return (
        <Item
            variant="pressable"
            size="sm"
            render={<button type="button" onClick={onOpen} data-attr="sidebar-open-ticket" />}
        >
            <ItemContent>
                <ItemTitle className={cn('w-full', unread > 0 && 'font-semibold')}>
                    <span className="truncate">
                        {ticket.last_message ? stripMarkdown(ticket.last_message) : 'No messages yet'}
                    </span>
                </ItemTitle>
                <ItemDescription>
                    {ticket.ticket_number && <span className="font-mono">#{ticket.ticket_number} · </span>}
                    <span translate="no">{dayjs(ticket.last_message_at ?? ticket.created_at).fromNow()}</span>
                </ItemDescription>
            </ItemContent>
            <ItemActions>
                {unread > 0 && (
                    <Badge variant="info" aria-label={`${unread} unread`}>
                        {unread}
                    </Badge>
                )}
                <Badge variant={ticketStatusBadgeVariant(ticket.status)}>
                    {sidePanelTicketFilterLabels[ticket.status]}
                </Badge>
            </ItemActions>
        </Item>
    )
}
