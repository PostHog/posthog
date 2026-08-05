import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCheckbox,
    LemonInputSelect,
    LemonMenu,
    LemonModal,
    LemonTag,
    LemonTextArea,
    Link,
} from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { Ticket } from '../../types'
import { customerLabel, mergeTicketModalLogic } from './mergeTicketModalLogic'

function ticketSummary(ticket: Ticket): string {
    return ticket.email_subject || ticket.last_message_text || 'No subject'
}

interface TicketActionsProps {
    sourceTicket: Ticket
    onMerged: () => void
}

/** "Actions" dropdown shown next to Save changes, plus the merge modal it opens. */
export function TicketActions({ sourceTicket, onMerged }: TicketActionsProps): JSX.Element {
    const logic = mergeTicketModalLogic({ sourceTicket, onMerged })
    const { openMergeModal } = useActions(logic)

    const alreadyMerged = !!sourceTicket.merged_into_id

    return (
        <>
            <LemonMenu
                placement="bottom-end"
                items={[
                    {
                        label: 'Merge into another ticket',
                        onClick: openMergeModal,
                        disabledReason: alreadyMerged
                            ? `Already merged into #${sourceTicket.merged_into_ticket_number}`
                            : undefined,
                    },
                ]}
            >
                <LemonButton size="small" type="secondary" sideIcon={<IconChevronDown />}>
                    Actions
                </LemonButton>
            </LemonMenu>
            <MergeTicketModal sourceTicket={sourceTicket} onMerged={onMerged} />
        </>
    )
}

function MergeTicketModal({ sourceTicket, onMerged }: TicketActionsProps): JSX.Element {
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

    const submitDisabledReason = !selectedTargetId
        ? 'Select a ticket to merge into'
        : isCrossCustomer && !acknowledgedCrossCustomer
          ? 'Confirm the customers are different'
          : undefined

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeMergeModal}
            title="Merge ticket"
            description="This ticket will be marked resolved, assigned to you, and linked to the ticket you pick."
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
            <div className="flex flex-col gap-4 min-w-[520px]">
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

                <div className="flex flex-col gap-2 border-t pt-3">
                    <div className="flex items-center justify-between">
                        <label className="font-semibold text-xs">Note on this ticket</label>
                        {selectedTarget && <LemonTag type="muted">links to #{selectedTarget.ticket_number}</LemonTag>}
                    </div>
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
                    {!sourceSendToCustomer && <span className="text-xs text-muted-alt">Added as a private note.</span>}
                </div>

                <div className="flex flex-col gap-2 border-t pt-3">
                    <div className="flex items-center justify-between">
                        <label className="font-semibold text-xs">
                            Note on {selectedTarget ? `ticket #${selectedTarget.ticket_number}` : 'the target ticket'}
                        </label>
                        <LemonTag type="muted">links to #{sourceTicket.ticket_number}</LemonTag>
                    </div>
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
                    {!targetSendToCustomer && <span className="text-xs text-muted-alt">Added as a private note.</span>}
                </div>

                {sourceTicket.merged_into_id && (
                    <LemonBanner type="info">
                        This ticket is already merged into{' '}
                        <Link to={urls.supportTicketDetail(sourceTicket.merged_into_ticket_number as number)}>
                            #{sourceTicket.merged_into_ticket_number}
                        </Link>
                        .
                    </LemonBanner>
                )}
            </div>
        </LemonModal>
    )
}
