import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconAI, IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonCard, LemonSelect, LemonTag, Link, Spinner } from '@posthog/lemon-ui'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { AssigneeIconDisplay, AssigneeLabelDisplay, AssigneeSelect } from '../../components/Assignee'
import { ChannelsTag } from '../../components/Channels/ChannelsTag'
import { ChatView } from '../../components/Chat/ChatView'
import { SlaDisplay } from '../../components/SlaDisplay'
import { TicketTags } from '../../components/TicketTags'
import { type TicketPriority, type TicketStatus, priorityOptions, statusOptionsWithoutAll } from '../../types'
import { ExceptionsPanel } from './ExceptionsPanel'
import { PreviousTicketsPanel } from './PreviousTicketsPanel'
import { RecentEventsPanel } from './RecentEventsPanel'
import { SessionRecordingPanel } from './SessionRecordingPanel'
import { StaffActionsPanel } from './StaffActionsPanel'
import { supportTicketSceneLogic } from './supportTicketSceneLogic'
import { TicketActivityPanel } from './TicketActivityPanel'

export const scene: SceneExport<{ ticketId: string }> = {
    component: SupportTicketScene,
    logic: supportTicketSceneLogic,
    productKey: ProductKey.CONVERSATIONS,
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
        tags,
        chatMessages,
        messagesLoading,
        messageSending,
        hasMoreMessages,
        olderMessagesLoading,
        eventsQuery,
        previousTickets,
        previousTicketsLoading,
        exceptionsQuery,
        chatPanelWidth,
        hasUnsavedChanges,
        draftContent,
        draftIsPrivate,
        snoozedUntil,
        suggesting,
    } = useValues(logic)
    const {
        setStatus,
        setPriority,
        setAssignee,
        setTags,
        setSnoozedUntil,
        sendMessage,
        updateTicket,
        loadOlderMessages,
        setDraftContent,
        setDraftIsPrivate,
        suggestReply,
    } = useActions(logic)

    const { user } = useValues(userLogic)
    const aiSuggestionEnabled = useFeatureFlag('PRODUCT_SUPPORT_AI_SUGGESTION')
    const { dataProcessingAccepted, dataProcessingApprovalDisabledReason } = useValues(maxGlobalLogic)
    const { preflight } = useValues(preflightLogic)
    const aiAvailable = preflight?.openai_available

    const aiDisabledReason = !aiAvailable
        ? 'AI features are not available on this instance'
        : !dataProcessingAccepted
          ? dataProcessingApprovalDisabledReason || 'AI data processing must be approved for your organization'
          : suggesting
            ? 'Generating suggestion...'
            : null

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
                        showPrivateOption
                        unreadCustomerCount={ticket?.unread_customer_count}
                        showDeliveryStatus={ticket?.channel_source === 'widget'}
                        draftContent={draftContent}
                        onDraftChange={setDraftContent}
                        isPrivate={draftIsPrivate}
                        onPrivateChange={setDraftIsPrivate}
                        minHeight="min(400px, calc(100svh - 320px))"
                        maxHeight="min(600px, calc(100svh - 320px))"
                        extraActions={
                            aiSuggestionEnabled ? (
                                <AIConsentPopoverWrapper>
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        icon={<IconAI />}
                                        onClick={suggestReply}
                                        loading={suggesting}
                                        disabledReason={aiDisabledReason}
                                    >
                                        Suggest reply
                                    </LemonButton>
                                </AIConsentPopoverWrapper>
                            ) : undefined
                        }
                    />
                    <div className="hidden lg:block">
                        <Resizer {...resizerLogicProps} className="z-20" />
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
                                        size="small"
                                        type="secondary"
                                        onClick={(e) => {
                                            e.stopPropagation()
                                            newInternalTab(urls.personByDistinctId(ticket.distinct_id))
                                        }}
                                    >
                                        View person
                                    </LemonButton>
                                </div>
                                <PersonDisplay
                                    person={
                                        ticket.person
                                            ? {
                                                  id: ticket.person.id,
                                                  distinct_id: ticket.distinct_id,
                                                  distinct_ids: ticket.person.distinct_ids,
                                                  // Merge anonymous_traits as fallback for missing person properties
                                                  properties: {
                                                      ...ticket.anonymous_traits,
                                                      ...ticket.person.properties,
                                                  },
                                              }
                                            : {
                                                  distinct_id: ticket.distinct_id,
                                                  properties: ticket.anonymous_traits || {},
                                              }
                                    }
                                    withIcon
                                />
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
                                        <ChannelsTag channel={ticket.channel_source} detail={ticket.channel_detail} />
                                    </span>
                                </div>
                            )}
                            {ticket?.channel_source === 'slack' &&
                                ticket?.slack_team_id &&
                                ticket?.slack_channel_id &&
                                ticket?.slack_thread_ts && (
                                    <div className="flex justify-between items-center">
                                        <span className="text-muted-alt">Slack thread</span>
                                        <Link
                                            to={`https://app.slack.com/client/${ticket.slack_team_id}/${ticket.slack_channel_id}/thread/${ticket.slack_channel_id}-${ticket.slack_thread_ts.replace('.', '')}`}
                                            target="_blank"
                                            className="text-xs"
                                        >
                                            <LemonTag type="highlight">Open in Slack</LemonTag>
                                        </Link>
                                    </div>
                                )}
                            {ticket?.channel_source === 'email' && ticket?.email_subject && (
                                <div className="flex justify-between items-start gap-2">
                                    <span className="text-muted-alt shrink-0">Subject</span>
                                    <span className="text-xs truncate text-right" title={ticket.email_subject}>
                                        {ticket.email_subject}
                                    </span>
                                </div>
                            )}
                            {ticket?.channel_source === 'email' && ticket?.email_from && (
                                <div className="flex justify-between items-start gap-2">
                                    <span className="text-muted-alt shrink-0">From</span>
                                    <span className="text-xs truncate text-right" title={ticket.email_from}>
                                        {ticket.email_from}
                                    </span>
                                </div>
                            )}
                            {ticket?.channel_source === 'email' &&
                                ticket?.cc_participants &&
                                ticket.cc_participants.length > 0 && (
                                    <div className="flex justify-between items-start gap-2">
                                        <span className="text-muted-alt shrink-0">CC</span>
                                        <span
                                            className="text-xs truncate text-right"
                                            title={ticket.cc_participants.join(', ')}
                                        >
                                            {ticket.cc_participants.join(', ')}
                                        </span>
                                    </div>
                                )}
                            {ticket?.channel_source === 'email' && ticket?.email_to && (
                                <div className="flex justify-between items-start gap-2">
                                    <span className="text-muted-alt shrink-0">To</span>
                                    <span className="text-xs truncate text-right" title={ticket.email_to}>
                                        {ticket.email_to}
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
                                    size="small"
                                    value={status}
                                    options={statusOptionsWithoutAll}
                                    onChange={(value: TicketStatus | null) => value && setStatus(value)}
                                    dropdownMatchSelectWidth={false}
                                />
                            </div>
                            <div className="flex justify-between items-center">
                                <span className="text-muted-alt">Priority</span>
                                <LemonSelect
                                    size="small"
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
                                            size="small"
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
                            {ticket?.sla_due_at && (
                                <div className="flex justify-between items-center">
                                    <span className="text-muted-alt">SLA</span>
                                    <SlaDisplay slaDueAt={ticket.sla_due_at} />
                                </div>
                            )}
                            <div className="flex justify-between items-center">
                                <span className="text-muted-alt">Snooze</span>
                                <LemonCalendarSelectInput
                                    value={snoozedUntil ? dayjs(snoozedUntil) : null}
                                    onChange={(date) =>
                                        setSnoozedUntil(date ? date.startOf('minute').toISOString() : null)
                                    }
                                    granularity="minute"
                                    selectionPeriod="upcoming"
                                    clearable
                                    placeholder="Not snoozed"
                                    buttonProps={{ size: 'small', type: 'secondary', fullWidth: false }}
                                />
                            </div>
                            <div className="flex justify-between items-center">
                                <span className="text-muted-alt">Tags</span>
                                <TicketTags tags={tags} onChange={setTags} saving={false} />
                            </div>
                        </div>
                        <div className="mt-3 pt-3 border-t flex justify-end">
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={() => updateTicket()}
                                disabledReason={!hasUnsavedChanges ? 'No changes to save' : undefined}
                            >
                                Save changes
                            </LemonButton>
                        </div>
                    </LemonCard>

                    {/* Staff Actions Panel */}
                    {user?.is_staff && ticket && <StaffActionsPanel />}

                    {/* Activity History Panel */}
                    {ticket?.id && <TicketActivityPanel ticketId={ticket.id} />}

                    {ticket?.channel_source === 'widget' && (
                        <>
                            {/* Session Recording Panel */}
                            <SessionRecordingPanel
                                sessionContext={ticket?.session_context}
                                distinctId={ticket?.distinct_id}
                            />

                            {/* Recent Events Panel */}
                            <RecentEventsPanel
                                eventsQuery={eventsQuery}
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
                        </>
                    )}
                </div>
            </div>
        </SceneContent>
    )
}
