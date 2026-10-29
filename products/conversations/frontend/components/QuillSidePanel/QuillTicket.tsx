import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconArrowLeft } from '@posthog/icons'
import { Badge, Button, Separator, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { sidePanelTicketFilterLabels } from '../../types'
import { sidepanelTicketsLogic } from '../SidePanel/sidepanelTicketsLogic'
import { QuillTicketComposer } from './QuillTicketComposer'
import { QuillTicketMessages } from './QuillTicketMessages'
import { ticketStatusBadgeVariant } from './ticketStatusBadgeVariant'

// Saves go to `ticketId`, not the open ticket, because a send can resolve after another ticket opens
function ReplyComposer({ ticketId }: { ticketId: string }): JSX.Element {
    const { messageSending } = useValues(sidepanelTicketsLogic)
    const { sendMessage, setTicketDraft } = useActions(sidepanelTicketsLogic)
    const initialDraft = useMemo(() => sidepanelTicketsLogic.values.currentTicketDraft, [])

    return (
        <QuillTicketComposer
            onSend={sendMessage}
            sending={messageSending}
            draftContent={initialDraft}
            onDraftChange={(content) => setTicketDraft(ticketId, content)}
        />
    )
}

export function QuillTicket(): JSX.Element {
    const { messages, messagesLoading, currentTicket, currentTicketHasDraft, composerRevision } =
        useValues(sidepanelTicketsLogic)
    const { setView, discardDraft } = useActions(sidepanelTicketsLogic)

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
                {currentTicketHasDraft && (
                    <Button
                        size="sm"
                        variant="link-muted"
                        className="ml-auto"
                        onClick={discardDraft}
                        data-attr="sidebar-discard-ticket-draft"
                    >
                        Discard draft
                    </Button>
                )}
            </div>
            <Separator />
            <QuillTicketMessages messages={messages} messagesLoading={messagesLoading} />
            <div className="shrink-0">
                {currentTicket && (
                    <ReplyComposer key={`${currentTicket.id}:${composerRevision}`} ticketId={currentTicket.id} />
                )}
            </div>
        </div>
    )
}
