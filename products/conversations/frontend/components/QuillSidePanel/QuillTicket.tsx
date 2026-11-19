import { useActions, useValues } from 'kea'

import { IconArrowLeft } from '@posthog/icons'
import { Badge, Button, Separator, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { sidePanelTicketFilterLabels } from '../../types'
import { sidepanelTicketsLogic } from '../SidePanel/sidepanelTicketsLogic'
import { QuillTicketComposer } from './QuillTicketComposer'
import { QuillTicketMessages } from './QuillTicketMessages'
import { ticketStatusBadgeVariant } from './ticketStatusBadgeVariant'

export function QuillTicket(): JSX.Element {
    const { messages, messagesLoading, messageSending, currentTicket } = useValues(sidepanelTicketsLogic)
    const { sendMessage, setView } = useActions(sidepanelTicketsLogic)

    return (
        <div className="flex min-h-0 flex-1 flex-col gap-2">
            <div className="flex shrink-0 items-center gap-2">
                <Tooltip>
                    <TooltipTrigger
                        delay={0}
                        render={
                            <Button
                                size="icon"
                                aria-label="Back to tickets"
                                onClick={() => setView('list')}
                                data-attr="sidebar-go-back-to-tickets"
                            />
                        }
                    >
                        <IconArrowLeft />
                    </TooltipTrigger>
                    <TooltipContent>Back to tickets</TooltipContent>
                </Tooltip>
                {currentTicket?.ticket_number && (
                    <Text size="xs" variant="muted" render={<span className="font-mono" />}>
                        #{currentTicket.ticket_number}
                    </Text>
                )}
                {currentTicket && (
                    <Badge variant={ticketStatusBadgeVariant(currentTicket.status)}>
                        {sidePanelTicketFilterLabels[currentTicket.status]}
                    </Badge>
                )}
            </div>
            <Separator />
            <QuillTicketMessages messages={messages} messagesLoading={messagesLoading} />
            <div className="shrink-0">
                <QuillTicketComposer onSend={sendMessage} sending={messageSending} />
            </div>
        </div>
    )
}
