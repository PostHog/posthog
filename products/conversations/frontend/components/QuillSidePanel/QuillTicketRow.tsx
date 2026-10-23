import { Badge, Card, Text } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { stripMarkdown } from 'lib/utils/markdown'

import { type ConversationTicket, sidePanelTicketFilterLabels } from '../../types'
import { ticketStatusBadgeVariant } from './ticketStatusBadgeVariant'

export function QuillTicketRow({ ticket, onOpen }: { ticket: ConversationTicket; onOpen: () => void }): JSX.Element {
    const unread = ticket.unread_count ?? 0
    return (
        <Card size="sm" className="p-0">
            <button
                type="button"
                onClick={onOpen}
                data-attr="sidebar-open-ticket"
                className="flex w-full min-w-0 cursor-pointer items-center gap-3 px-3 py-2.5 text-start hover:bg-fill-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/30"
            >
                <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <Text
                        size="sm"
                        weight={unread > 0 ? 'semibold' : 'normal'}
                        render={<span />}
                        className="block truncate"
                    >
                        {ticket.last_message ? stripMarkdown(ticket.last_message) : 'No messages yet'}
                    </Text>
                    <Text size="xs" variant="muted" render={<span />} className="block truncate">
                        {ticket.ticket_number && <span className="font-mono">#{ticket.ticket_number} · </span>}
                        <TZLabel time={ticket.last_message_at ?? ticket.created_at} showPopover={false} />
                    </Text>
                </span>
                <span className="flex shrink-0 items-center gap-1">
                    {unread > 0 && (
                        <Badge variant="info" aria-label={`${unread} unread`}>
                            {unread}
                        </Badge>
                    )}
                    <Badge variant={ticketStatusBadgeVariant(ticket.status)}>
                        {sidePanelTicketFilterLabels[ticket.status]}
                    </Badge>
                </span>
            </button>
        </Card>
    )
}
