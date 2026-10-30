import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonTag } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { MessageInput } from '../Chat/MessageInput'
import { MessageList } from '../Chat/MessageList'
import { sidepanelTicketsLogic } from './sidepanelTicketsLogic'

interface TicketProps {
    /** Hidden in master-detail layouts where the list stays visible alongside the thread */
    showBackButton?: boolean
    /** Lets master-detail layouts show the back button only at widths where the panes stack */
    backButtonClassName?: string
    /** Fill a bounded parent (the full-screen scene pane). The side panel must not opt in: its
     *  parent height is auto, and overflow-hidden plus a 400px message cap would leave an empty
     *  card below the composer. */
    fillParent?: boolean
    messagesMinHeight?: string
    messagesMaxHeight?: string
}

// Saves go to `ticketId`, not the open ticket, because a send can resolve after another ticket opens
function ReplyComposer({ ticketId }: { ticketId: string }): JSX.Element {
    const { messageSending } = useValues(sidepanelTicketsLogic)
    const { sendMessage, setTicketDraft } = useActions(sidepanelTicketsLogic)
    const initialDraft = useMemo(() => sidepanelTicketsLogic.values.currentTicketDraft, [])

    return (
        <MessageInput
            onSendMessage={(content, _richContent, _isPrivate, onSuccess) => sendMessage(content, onSuccess)}
            messageSending={messageSending}
            draftContent={initialDraft}
            onDraftChange={(content) => setTicketDraft(ticketId, content)}
        />
    )
}

export function Ticket({
    showBackButton = true,
    backButtonClassName,
    fillParent = false,
    messagesMinHeight = fillParent ? '0' : '300px',
    messagesMaxHeight = fillParent ? 'none' : '400px',
}: TicketProps): JSX.Element {
    const { messages, messagesLoading, currentTicket, currentTicketHasDraft, composerRevision } =
        useValues(sidepanelTicketsLogic)
    const { setView, discardDraft } = useActions(sidepanelTicketsLogic)

    return (
        <div
            className={cn(
                'flex flex-col h-full bg-surface-primary border rounded-lg p-2',
                fillParent && 'min-h-0 overflow-hidden'
            )}
        >
            <div className="flex items-center gap-2 shrink-0">
                {showBackButton && (
                    <LemonButton
                        icon={<IconArrowLeft />}
                        size="small"
                        className={backButtonClassName}
                        onClick={() => setView('list')}
                    />
                )}
                {currentTicket?.ticket_number && (
                    <span className="text-xs font-mono text-muted-alt">#{currentTicket.ticket_number}</span>
                )}
                <LemonTag
                    type={
                        currentTicket?.status === 'resolved'
                            ? 'success'
                            : currentTicket?.status === 'new'
                              ? 'primary'
                              : 'default'
                    }
                    size="small"
                >
                    {currentTicket?.status === 'on_hold' ? 'On hold' : currentTicket?.status}
                </LemonTag>
                {currentTicketHasDraft && (
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        className="ml-auto"
                        onClick={discardDraft}
                        data-attr="sidebar-discard-ticket-draft"
                    >
                        Discard draft
                    </LemonButton>
                )}
            </div>
            <LemonDivider />
            <MessageList
                messages={messages}
                messagesLoading={messagesLoading}
                emptyMessage="No messages yet."
                minHeight={messagesMinHeight}
                maxHeight={messagesMaxHeight}
                className="mb-3"
                isCustomerView
            />
            <div className="border-t pt-3 shrink-0">
                {currentTicket && (
                    <ReplyComposer key={`${currentTicket.id}:${composerRevision}`} ticketId={currentTicket.id} />
                )}
            </div>
        </div>
    )
}
