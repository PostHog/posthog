import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useRef } from 'react'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonCard, LemonSelect, Link, Spinner } from '@posthog/lemon-ui'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { TZLabel } from 'lib/components/TZLabel'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { AssigneeIconDisplay, AssigneeLabelDisplay, AssigneeSelect } from '../../components/Assignee'
import { ChannelsTag } from '../../components/Channels/ChannelsTag'
import { ChatView } from '../../components/Chat/ChatView'
import { type TicketPriority, type TicketStatus, priorityOptions, statusOptionsWithoutAll } from '../../types'
import { ExceptionsPanel } from './ExceptionsPanel'
import { PreviousTicketsPanel } from './PreviousTicketsPanel'
import { RecentEventsPanel } from './RecentEventsPanel'
import { SessionRecordingPanel } from './SessionRecordingPanel'
import { supportTicketSceneLogic } from './supportTicketSceneLogic'

export const scene: SceneExport<{ ticketId: string }> = {
    component: SupportTicketScene,
    logic: supportTicketSceneLogic,
    paramsToProps: ({ params: { ticketId } }) => ({ ticketId: ticketId || 'new' }),
}

export function SupportTicketScene({ ticketId }: { ticketId: string }): JSX.Element {
    const logic = supportTicketSceneLogic({ id: ticketId || 'new' })
    const {
        ticket,
        ticketLoading,
        status,
        priority,
        assignee,
        chatMessages,
        messagesLoading,
        messageSending,
        hasMoreMessages,
        olderMessagesLoading,
        eventsQuery,
        personLoading,
        previousTickets,
        previousTicketsLoading,
        exceptionsQuery,
        chatPanelWidth,
    } = useValues(logic)
    const { setStatus, setPriority, setAssignee, sendMessage, updateTicket, loadOlderMessages } = useActions(logic)
    const { push } = useActions(router)

    const chatPanelRef = useRef<HTMLDivElement>(null)

    const resizerLogicProps: ResizerLogicProps = {
        containerRef: chatPanelRef,
        logicKey: 'support-ticket-resizer',
        persistent: true,
        placement: 'right',
    }

    const { desiredSize } = useValues(resizerLogic(resizerLogicProps))

    if (ticketLoading) {
        return (
            <SceneContent>
                <div className="flex items-center justify-center h-96">
                    <Spinner className="text-4xl" />
                </div>
            </SceneContent>
        )
    }

    const isNewTicket = ticketId === 'new'

    if (!ticket && !isNewTicket) {
        return (
            <SceneContent>
                <div className="flex items-center justify-center h-96">
                    <div className="text-center">
                        <h2 className="text-xl font-semibold mb-2">Ticket not found</h2>
                        <LemonButton type="primary" to={urls.supportTickets()}>
                            Back to tickets
                        </LemonButton>
                    </div>
                </div>
            </SceneContent>
        )
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={`Ticket: ${ticket?.ticket_number?.toString() || ticket?.id || ''}`}
                description=""
                resourceType={{ type: 'conversation' }}
                forceBackTo={{
                    name: 'Ticket list',
                    path: urls.supportTickets(),
                    key: 'supportTickets',
                }}
            />

            <div className="flex flex-col lg:flex-row items-start">
                <div
                    style={{ width: chatPanelWidth(desiredSize) }}
                    className="relative shrink-0 pr-2 max-w-full lg:max-w-[calc(100%-300px)] mb-4 lg:mb-0"
                    ref={chatPanelRef}
                >
                    {/* Main conversation area */}
                    <ChatView
                        messages={chatMessages}
                        messagesLoading={messagesLoading}
                        messageSending={messageSending}
                        hasMoreMessages={hasMoreMessages}
                        olderMessagesLoading={olderMessagesLoading}
                        onSendMessage={sendMessage}
                        onLoadOlderMessages={loadOlderMessages}
                    />
                    <div className="hidden lg:block">
                        <Resizer {...resizerLogicProps} />
                    </div>
                </div>

                {/* Sidebar with all metadata */}
                <div className="space-y-4 flex-1 min-w-[300px] pl-2">
                    <LemonCard hoverEffect={false} className="p-3">
                        {/* Customer */}
                        {ticket?.distinct_id && (
                            <>
                                <div className="flex items-center justify-between mb-3">
                                    <h3 className="text-sm font-semibold">Customer</h3>
                                    <LemonButton
                                        size="xsmall"
                                        type="secondary"
                                        onClick={() => push(urls.personByDistinctId(ticket.distinct_id))}
                                    >
                                        View person
                                    </LemonButton>
                                </div>
                                <PersonDisplay person={{ distinct_id: ticket.distinct_id }} withIcon />
                                <div className="my-3 border-t" />
                            </>
                        )}

                        {/* Ticket info */}
                        <h3 className="text-sm font-semibold mb-2">Ticket info</h3>
                        <div className="space-y-2 text-xs">
                            {ticket?.created_at && (
                                <div className="flex justify-between">
                                    <span className="text-muted-alt">Created</span>
                                    <span>
                                        <TZLabel time={ticket.created_at} />
                                    </span>
                                </div>
                            )}
                            {ticket?.updated_at && (
                                <div className="flex justify-between">
                                    <span className="text-muted-alt">Updated</span>
                                    <span>
                                        <TZLabel time={ticket.updated_at} />
                                    </span>
                                </div>
                            )}
                            {ticket?.channel_source && (
                                <div className="flex justify-between">
                                    <span className="text-muted-alt">Channel</span>
                                    <span className="capitalize">
                                        <ChannelsTag channel={ticket.channel_source} />
                                    </span>
                                </div>
                            )}
                            {ticket?.session_context?.current_url && (
                                <div className="flex justify-between items-start gap-2">
                                    <span className="text-muted-alt shrink-0">Page URL</span>
                                    <Link
                                        to={ticket.session_context.current_url}
                                        target="_blank"
                                        className="text-xs truncate text-right"
                                        title={ticket.session_context.current_url}
                                    >
                                        {ticket.session_context.current_url}
                                    </Link>
                                </div>
                            )}
                            <div className="flex justify-between items-center">
                                <span className="text-muted-alt">Status</span>
                                <LemonSelect
                                    size="xsmall"
                                    value={status}
                                    options={statusOptionsWithoutAll}
                                    onChange={(value: TicketStatus | null) => value && setStatus(value)}
                                    dropdownMatchSelectWidth={false}
                                />
                            </div>
                            <div className="flex justify-between items-center">
                                <span className="text-muted-alt">Priority</span>
                                <LemonSelect
                                    size="xsmall"
                                    value={priority}
                                    options={priorityOptions}
                                    onChange={(value: TicketPriority | null) => value && setPriority(value)}
                                    dropdownMatchSelectWidth={false}
                                />
                            </div>
                            <div className="flex justify-between items-center">
                                <span className="text-muted-alt">Assignee</span>
                                <AssigneeSelect assignee={assignee} onChange={setAssignee}>
                                    {(resolvedAssignee, isOpen) => (
                                        <LemonButton
                                            size="xsmall"
                                            type="secondary"
                                            active={isOpen}
                                            sideIcon={<IconChevronDown />}
                                        >
                                            <span className="flex items-center gap-1">
                                                <AssigneeIconDisplay assignee={resolvedAssignee} size="small" />
                                                <AssigneeLabelDisplay assignee={resolvedAssignee} size="small" />
                                            </span>
                                        </LemonButton>
                                    )}
                                </AssigneeSelect>
                            </div>
                        </div>
                        <div className="mt-3 pt-3 border-t flex justify-end">
                            <LemonButton type="primary" size="small" onClick={() => updateTicket()}>
                                Save changes
                            </LemonButton>
                        </div>
                    </LemonCard>

                    {/* Session Recording Panel */}
                    <SessionRecordingPanel sessionContext={ticket?.session_context} distinctId={ticket?.distinct_id} />

                    {/* Recent Events Panel */}
                    <RecentEventsPanel
                        eventsQuery={eventsQuery}
                        personLoading={personLoading}
                        distinctId={ticket?.distinct_id}
                        sessionId={ticket?.session_id}
                    />

                    {/* Exceptions Panel */}
                    <ExceptionsPanel
                        exceptionsQuery={exceptionsQuery}
                        sessionId={ticket?.session_id}
                        distinctId={ticket?.distinct_id}
                    />

                    {/* Previous Tickets Panel */}
                    <PreviousTicketsPanel
                        previousTickets={previousTickets}
                        previousTicketsLoading={previousTicketsLoading}
                    />
                </div>
            </div>
        </SceneContent>
    )
}
