import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCheckbox,
    LemonInputSelect,
    LemonMenu,
    LemonModal,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { MessageList } from '../../components/Chat/MessageList'
import type { ChatMessage, Ticket } from '../../types'
import { customerLabel, mergeTicketModalLogic } from './mergeTicketModalLogic'

function ticketSummary(ticket: Ticket): string {
    return ticket.email_subject || ticket.last_message_text || 'No subject'
}

interface TicketActionsProps {
    sourceTicket: Ticket
    onMerged: () => void
    /** Blocks merging outright, e.g. when the user lacks edit access to the ticket. */
    disabledReason?: string
}

function ConversationPane({
    title,
    subtitle,
    messages,
    loading,
    emptyMessage,
}: {
    title: string
    subtitle?: string
    messages: ChatMessage[]
    loading: boolean
    emptyMessage: string
}): JSX.Element {
    return (
        <div className="flex flex-col flex-1 min-w-0 border rounded overflow-hidden">
            <div className="px-3 py-2 border-b bg-surface-secondary">
                <div className="text-sm font-semibold truncate">{title}</div>
                {subtitle && <div className="text-xs text-muted-alt truncate">{subtitle}</div>}
            </div>
            <MessageList
                messages={messages}
                messagesLoading={loading}
                emptyMessage={emptyMessage}
                minHeight="300px"
                maxHeight="45vh"
                className="px-3 py-2"
            />
        </div>
    )
}

/** "Actions" dropdown shown next to Save changes, plus the merge modal it opens. */
export function TicketActions({ sourceTicket, onMerged, disabledReason }: TicketActionsProps): JSX.Element {
    const logic = mergeTicketModalLogic({ sourceTicket, onMerged })
    const { openMergeModal } = useActions(logic)

    const alreadyMerged = !!sourceTicket.merged_into_id
    const hasMergedTickets = (sourceTicket.merged_tickets?.length ?? 0) > 0
    const mergeDisabledReason =
        disabledReason ??
        (alreadyMerged
            ? `Already merged into #${sourceTicket.merged_into_ticket_number}`
            : hasMergedTickets
              ? "Other tickets are merged into this one, so it can't be merged elsewhere"
              : undefined)

    return (
        <>
            <LemonMenu
                placement="bottom-end"
                items={[
                    {
                        label: 'Merge into another ticket',
                        onClick: openMergeModal,
                        disabledReason: mergeDisabledReason,
                    },
                ]}
            >
                <LemonButton size="small" type="secondary" sideIcon={<IconChevronDown />}>
                    Actions
                </LemonButton>
            </LemonMenu>
            <MergeTicketModal sourceTicket={sourceTicket} onMerged={onMerged} disabledReason={disabledReason} />
        </>
    )
}

function MergeTicketModal({ sourceTicket, onMerged, disabledReason }: TicketActionsProps): JSX.Element {
    const logic = mergeTicketModalLogic({ sourceTicket, onMerged })
    const {
        isOpen,
        searchQuery,
        selectedTargetId,
        selectedTarget,
        targetOptions,
        suggestedTicketsLoading,
        searchResultsLoading,
        isCrossCustomer,
        acknowledgedCrossCustomer,
        sourceNote,
        targetNote,
        sourceSendToCustomer,
        targetSendToCustomer,
        submitting,
        sourceChatMessages,
        sourceMessagesLoading,
        targetChatMessages,
        targetMessagesLoading,
    } = useValues(logic)
    const {
        closeMergeModal,
        setSearchQuery,
        setSelectedTargetId,
        setSourceNote,
        setTargetNote,
        setSourceSendToCustomer,
        setTargetSendToCustomer,
        setAcknowledgedCrossCustomer,
        submitMerge,
    } = useActions(logic)

    const options = targetOptions.map((ticket) => ({
        key: ticket.id,
        label: `#${ticket.ticket_number} ${ticketSummary(ticket)}`,
        labelComponent: (
            <div className="flex flex-col gap-0.5 py-0.5">
                <div className="flex items-center gap-1.5">
                    <span className="font-semibold">#{ticket.ticket_number}</span>
                    <span className="truncate">{ticketSummary(ticket)}</span>
                </div>
                <span className="text-xs text-muted-alt truncate">{customerLabel(ticket)}</span>
            </div>
        ),
    }))

    const submitDisabledReason =
        disabledReason ??
        (!selectedTargetId
            ? 'Select a ticket to merge into'
            : isCrossCustomer && !acknowledgedCrossCustomer
              ? 'Confirm the customers are different'
              : undefined)

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeMergeModal}
            title="Merge ticket"
            description="This ticket will be marked resolved, assigned to you, and linked to the ticket you pick."
            width="min(1100px, 90vw)"
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeMergeModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitMerge}
                        loading={submitting}
                        disabledReason={submitDisabledReason}
                    >
                        Merge ticket
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <div className="flex flex-col gap-1">
                    <label className="font-semibold text-xs">Merge into</label>
                    <LemonInputSelect
                        mode="single"
                        value={selectedTargetId ? [selectedTargetId] : []}
                        options={options}
                        onChange={(value) => setSelectedTargetId(value[0] ?? null)}
                        onInputChange={setSearchQuery}
                        loading={suggestedTicketsLoading || searchResultsLoading}
                        disableFiltering
                        placeholder="Search by ticket number, subject, or message…"
                        title={searchQuery.trim() ? 'Search results' : 'From this customer'}
                        emptyStateComponent={
                            <span className="text-muted-alt">
                                {searchQuery.trim() ? 'No matching tickets' : 'No other tickets from this customer'}
                            </span>
                        }
                    />
                </div>

                {/* Side-by-side conversations: current ticket on the left, chosen target on the right. */}
                <div className="flex gap-3">
                    <ConversationPane
                        title={`This ticket · #${sourceTicket.ticket_number}`}
                        subtitle={customerLabel(sourceTicket)}
                        messages={sourceChatMessages}
                        loading={sourceMessagesLoading}
                        emptyMessage="No messages"
                    />
                    <ConversationPane
                        title={
                            selectedTarget
                                ? `Merge into · #${selectedTarget.ticket_number}`
                                : 'Select a ticket to merge into'
                        }
                        subtitle={selectedTarget ? customerLabel(selectedTarget) : undefined}
                        messages={targetChatMessages}
                        loading={targetMessagesLoading}
                        emptyMessage={selectedTarget ? 'No messages' : 'Pick a ticket on the left to preview it here'}
                    />
                </div>

                {selectedTarget && isCrossCustomer && (
                    <LemonBanner type="warning">
                        <p className="mb-2">These tickets are from different customers. Merge only if you're sure.</p>
                        <div className="flex flex-col gap-1 text-sm mb-2">
                            <span>
                                This ticket: <strong>{customerLabel(sourceTicket)}</strong>
                            </span>
                            <span>
                                #{selectedTarget.ticket_number}: <strong>{customerLabel(selectedTarget)}</strong>
                            </span>
                        </div>
                        <LemonCheckbox
                            checked={acknowledgedCrossCustomer}
                            onChange={setAcknowledgedCrossCustomer}
                            label="I understand these are different customers"
                        />
                    </LemonBanner>
                )}

                <div className="flex gap-3">
                    <div className="flex flex-col gap-2 flex-1 min-w-0">
                        <label className="font-semibold text-xs">Note on this ticket</label>
                        <LemonTextArea
                            value={sourceNote}
                            onChange={setSourceNote}
                            placeholder="Optional message to add alongside the link…"
                            minRows={2}
                        />
                        <LemonCheckbox
                            checked={sourceSendToCustomer}
                            onChange={setSourceSendToCustomer}
                            label="Send to the customer"
                        />
                        {!sourceSendToCustomer && (
                            <span className="text-xs text-muted-alt">Added as a private note.</span>
                        )}
                    </div>

                    <div className="flex flex-col gap-2 flex-1 min-w-0">
                        <label className="font-semibold text-xs">
                            Note on {selectedTarget ? `#${selectedTarget.ticket_number}` : 'the target ticket'}
                        </label>
                        <LemonTextArea
                            value={targetNote}
                            onChange={setTargetNote}
                            placeholder="Optional message to add alongside the link…"
                            minRows={2}
                        />
                        <LemonCheckbox
                            checked={targetSendToCustomer}
                            onChange={setTargetSendToCustomer}
                            label="Send to the customer"
                        />
                        {!targetSendToCustomer && (
                            <span className="text-xs text-muted-alt">Added as a private note.</span>
                        )}
                    </div>
                </div>
            </div>
        </LemonModal>
    )
}
