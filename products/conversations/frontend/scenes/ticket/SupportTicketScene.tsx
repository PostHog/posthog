import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { useRef } from 'react'

import { LemonCard, LemonModal, Link, Spinner } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { TZLabel } from 'lib/components/TZLabel'
import {
    Badge,
    Button,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectTriggerIcon,
    SelectValue,
} from 'lib/ui/quill'
import { getAccessControlDisabledReason, accessLevelSatisfied } from 'lib/utils/accessControlUtils'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType, Breadcrumb } from '~/types'

import { AssigneeIconDisplay, AssigneeLabelDisplay, AssigneeSelect } from '../../components/Assignee'
import { ChannelsTag, getChannelThreadUrl } from '../../components/Channels/ChannelsTag'
import { ChatView } from '../../components/Chat/ChatView'
import { SupportMarkdown } from '../../components/Editor'
import { IdentityBadge } from '../../components/IdentityBadge/IdentityBadge'
import { TicketSnoozeButton } from '../../components/TicketSnoozeButton/TicketSnoozeButton'
import { TicketTags } from '../../components/TicketTags'
import { type TicketPriority, type TicketStatus, priorityOptions, statusOptionsWithoutAll } from '../../types'
import { AIPanel } from './AIPanel'
import { ExceptionsPanel } from './ExceptionsPanel'
import { PreviousTicketsPanel } from './PreviousTicketsPanel'
import { RecentEventsPanel } from './RecentEventsPanel'
import { RelatedGroupsPanel } from './RelatedGroupsPanel'
import { SessionRecordingPanel } from './SessionRecordingPanel'
import { StaffActionsPanel } from './StaffActionsPanel'
import { supportTicketSceneLogic } from './supportTicketSceneLogic'
import { useDiscussionTimelineExtras } from './ThreadDiscussions'
import { reportTimelineExtras } from './ThreadReports'
import { TicketActivityPanel } from './TicketActivityPanel'

// The list's filters / saved view ride along in the ticket page's query string
// (the ticket row carries them through on navigation). Rebuild the list URL from
// them so the back arrow returns to the view the user came from rather than the
// unfiltered ticket list.
export function ticketListBackTo(searchParams: Record<string, any>): Breadcrumb {
    return {
        name: 'Ticket list',
        path: combineUrl(urls.supportTickets(), searchParams).url,
        key: 'supportTickets',
    }
}

export const scene: SceneExport<{ ticketId: string; id: string }> = {
    component: SupportTicketScene,
    logic: supportTicketSceneLogic,
    productKey: ProductKey.CONVERSATIONS,
    // `id` must match supportTicketSceneLogic's `key((props) => props.id)` so the logic instance
    // App.tsx binds via BindLogic (and that the side panel context reads) is the same keyed
    // instance the component builds directly — otherwise the side panel reads a never-populated
    // logic instance and the access control tab never appears.
    paramsToProps: ({ params: { ticketId } }) => ({ ticketId: ticketId || 'new', id: ticketId || 'new' }),
}

// The rendered label is "<Send|Attach> and set <statusLabel>", depending on the private note checkbox
const SEND_AND_SET_STATUS_OPTIONS: { value: TicketStatus; statusLabel: string }[] = [
    { value: 'pending', statusLabel: 'pending' },
    { value: 'on_hold', statusLabel: 'on hold' },
    { value: 'resolved', statusLabel: 'resolved' },
]

export function SupportTicketScene({ ticketId }: { ticketId: string }): JSX.Element {
    const logic = supportTicketSceneLogic({ id: ticketId || 'new' })
    const {
        ticket,
        person,
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
        linkedReports,
        exceptionsQuery,
        chatPanelWidth,
        hasUnsavedChanges,
        unsavedTicketChanges,
        ticketUpdating,
        draftContent,
        draftIsPrivate,
        draftModeEnabled,
        replyRecipientDescription,
        snoozedUntil,
        knowledgeGaps,
        knowledgeGapsLoading,
        emailReplyBlockedReason,
        latestAiMessage,
        feedbackByMessageId,
        editingMessageId,
        discussionsEnabled,
        fullEmailContent,
        fullEmailContentLoading,
        fullEmailMessageId,
    } = useValues(logic)
    // The list's filters / saved view ride along in this page's query string
    // (the ticket row carries them through on navigation). Preserve them on the
    // back arrow so it returns to the view the user came from rather than the
    // unfiltered ticket list (see ticketListBackTo).
    const { searchParams } = useValues(router)
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
        setDraftModeEnabled,
        dismissKnowledgeGap,
        submitAiReplyFeedback,
        startEditingMessage,
        cancelEditingMessage,
        deleteMessage,
        loadFullEmail,
        closeFullEmail,
    } = useActions(logic)

    const { user } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const aiSuggestionsEnabled = !!currentTeam?.conversations_settings?.ai_suggestions_enabled

    const conversationsSettingsUrl = urls.settings('environment-conversations', 'conversations-general')
    const replyDisabledReason: JSX.Element | undefined = emailReplyBlockedReason
        ? {
              email_disabled: (
                  <>
                      Replies can't be emailed because this project has no connected email channel.{' '}
                      <Link to={conversationsSettingsUrl}>Connect an email address</Link> to reply to this customer.
                  </>
              ),
              no_recipient: (
                  <>
                      This ticket has no customer email address, so a reply can't be delivered. You can still attach a
                      private note.
                  </>
              ),
              no_channel: (
                  <>
                      This ticket isn't linked to any of your email channels, so replies can't be sent.{' '}
                      <Link to={conversationsSettingsUrl}>Manage email channels</Link>
                  </>
              ),
          }[emailReplyBlockedReason]
        : undefined

    const canEditTicket = accessLevelSatisfied(
        AccessControlResourceType.Ticket,
        ticket?.user_access_level ?? AccessControlLevel.None,
        AccessControlLevel.Editor
    )

    const sendDisabledReason =
        getAccessControlDisabledReason(
            AccessControlResourceType.Ticket,
            AccessControlLevel.Editor,
            ticket?.user_access_level
        ) ?? undefined

    const chatPanelRef = useRef<HTMLDivElement>(null)

    const resizerLogicProps: ResizerLogicProps = {
        containerRef: chatPanelRef,
        logicKey: 'support-ticket-resizer',
        persistent: true,
        placement: 'right',
    }

    const { desiredSize } = useValues(resizerLogic(resizerLogicProps))

    // Above the early returns below: this scene renders a spinner and a not-found state before the
    // thread, and a hook can't be called on only some of those paths.
    const discussionExtras = useDiscussionTimelineExtras(ticket?.id, discussionsEnabled)

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
                        <Button variant="primary" onClick={() => router.actions.push(urls.supportTickets())}>
                            Back to tickets
                        </Button>
                    </div>
                </div>
            </SceneContent>
        )
    }

    return (
        <SceneContent className="flex-1 min-h-0 pb-4">
            <SceneTitleSection
                name={`Ticket: ${ticket?.ticket_number?.toString() || ticket?.id || ''}`}
                nameSuffix={
                    ticket && ticket.identity_verified !== true ? (
                        <IdentityBadge verified={ticket.identity_verified} />
                    ) : undefined
                }
                description=""
                resourceType={{ type: 'conversation' }}
                forceBackTo={ticketListBackTo(searchParams)}
            />
            <LemonModal title="Full email" isOpen={fullEmailMessageId !== null} onClose={closeFullEmail}>
                {fullEmailContentLoading ? (
                    <div className="flex h-40 items-center justify-center">
                        <Spinner />
                    </div>
                ) : (
                    <div className="max-h-96 overflow-y-auto break-words text-sm">
                        <SupportMarkdown disableImages>{fullEmailContent ?? ''}</SupportMarkdown>
                    </div>
                )}
            </LemonModal>

            {/* Overflow clipping is only safe side-by-side, where the thread has a bounded height.
                Stacked, the thread is content-sized; clipping here would collapse it. */}
            <div className="flex flex-col gap-y-4 @min-[48rem]/main-content:flex-row @min-[48rem]/main-content:flex-1 @min-[48rem]/main-content:min-h-0 @min-[48rem]/main-content:overflow-hidden">
                <div
                    style={{ width: chatPanelWidth(desiredSize) }}
                    className="relative shrink-0 max-w-full min-h-80  @min-[48rem]/main-content:pr-2 @min-[48rem]/main-content:max-w-[calc(100%-300px)] @min-[48rem]/main-content:h-full @min-[48rem]/main-content:min-h-0 @min-[48rem]/main-content:flex @min-[48rem]/main-content:flex-col"
                    ref={chatPanelRef}
                >
                    {/* Main conversation area */}
                    <ChatView
                        fillParent
                        collapseUntilActive
                        threadId={ticketId}
                        threadExtras={[...reportTimelineExtras(linkedReports), ...discussionExtras]}
                        messages={chatMessages}
                        messagesLoading={messagesLoading}
                        messageSending={messageSending}
                        hasMoreMessages={hasMoreMessages}
                        olderMessagesLoading={olderMessagesLoading}
                        onSendMessage={sendMessage}
                        onLoadOlderMessages={loadOlderMessages}
                        channel={ticket?.channel_source}
                        showPrivateOption
                        unreadCustomerCount={ticket?.unread_customer_count}
                        showDeliveryStatus={ticket?.channel_source === 'widget'}
                        draftContent={draftContent}
                        onDraftChange={setDraftContent}
                        isPrivate={draftIsPrivate}
                        onPrivateChange={setDraftIsPrivate}
                        draftMode={draftModeEnabled}
                        onDraftModeChange={setDraftModeEnabled}
                        sendConfirmationMessage={`This will send to ${replyRecipientDescription}`}
                        sendAndSetStatusOptions={ticket ? SEND_AND_SET_STATUS_OPTIONS : undefined}
                        unsavedTicketChanges={unsavedTicketChanges}
                        replyDisabledReason={replyDisabledReason}
                        sendDisabledReason={sendDisabledReason}
                        latestAiMessageId={latestAiMessage?.id ?? null}
                        feedbackByMessageId={feedbackByMessageId}
                        showAiReplyFeedback={aiSuggestionsEnabled}
                        aiReplyFeedbackDisabledReason={sendDisabledReason}
                        onSubmitAiReplyFeedback={submitAiReplyFeedback}
                        currentUserId={user?.id ?? null}
                        canEditTicket={canEditTicket}
                        editingMessageId={editingMessageId}
                        onEditMessage={startEditingMessage}
                        onDeleteMessage={deleteMessage}
                        onCancelEdit={cancelEditingMessage}
                        fullEmailLoadingMessageId={fullEmailContentLoading ? fullEmailMessageId : null}
                        onViewFullEmail={loadFullEmail}
                    />
                    <div className="hidden @min-[48rem]/main-content:block">
                        <Resizer {...resizerLogicProps} className="z-20" />
                    </div>
                </div>

                {/* Sidebar with all metadata */}
                <div className="space-y-4 flex-1 min-w-[300px] @min-[48rem]/main-content:h-full @min-[48rem]/main-content:pl-2 @min-[48rem]/main-content:min-h-0 @min-[48rem]/main-content:overflow-y-auto">
                    <LemonCard hoverEffect={false} className="p-3">
                        {/* Customer */}
                        {ticket?.distinct_id && (
                            <>
                                <div className="flex items-center justify-between mb-3">
                                    <h3 className="text-sm font-semibold">Customer</h3>
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={(e) => {
                                            e.stopPropagation()
                                            newInternalTab(urls.personByDistinctId(ticket.distinct_id))
                                        }}
                                    >
                                        View person
                                    </Button>
                                </div>
                                <div className="flex items-center flex-wrap gap-2">
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
                                        withCopyEmailButton
                                        withComposeTicketButton
                                    />
                                    <IdentityBadge verified={ticket.identity_verified} />
                                </div>
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
                                        <ChannelsTag
                                            channel={ticket.channel_source}
                                            detail={ticket.channel_detail}
                                            to={getChannelThreadUrl(ticket)}
                                        />
                                    </span>
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
                            {ticket?.channel_source === 'email' && ticket?.email_to && (
                                <div className="flex justify-between items-start gap-2">
                                    <span className="text-muted-alt shrink-0">To</span>
                                    <span className="text-xs truncate text-right" title={ticket.email_to}>
                                        {ticket.email_to}
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
                            {ticket?.channel_source === 'github' &&
                                ticket?.github_repo &&
                                ticket?.github_issue_number && (
                                    <div className="flex justify-between items-center">
                                        <span className="text-muted-alt">GitHub issue</span>
                                        <Link
                                            to={`https://github.com/${ticket.github_repo}/issues/${ticket.github_issue_number}`}
                                            target="_blank"
                                            className="text-xs"
                                        >
                                            <Badge>
                                                {ticket.github_repo}#{ticket.github_issue_number}
                                            </Badge>
                                        </Link>
                                    </div>
                                )}
                            {ticket?.zendesk_ticket_id && (
                                <div className="flex justify-between items-center">
                                    <span className="text-muted-alt">Zendesk ID</span>
                                    <Badge>#{ticket.zendesk_ticket_id}</Badge>
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
                                <Select
                                    value={status}
                                    disabled={!!sendDisabledReason}
                                    onValueChange={(value: TicketStatus | null) => {
                                        if (value) {
                                            setStatus(value)
                                        }
                                    }}
                                >
                                    <SelectTrigger size="sm" title={sendDisabledReason ?? undefined}>
                                        <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent align="end" alignItemWithTrigger={false}>
                                        {statusOptionsWithoutAll.map((option) => (
                                            <SelectItem key={option.value} value={option.value}>
                                                {option.label}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>
                            <div className="flex justify-between items-center">
                                <span className="text-muted-alt">Priority</span>
                                <Select
                                    value={priority}
                                    disabled={!!sendDisabledReason}
                                    onValueChange={(value: TicketPriority | null) => {
                                        if (value) {
                                            setPriority(value)
                                        }
                                    }}
                                >
                                    <SelectTrigger size="sm" title={sendDisabledReason ?? undefined}>
                                        <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent align="end" alignItemWithTrigger={false}>
                                        {priorityOptions.map((option) => (
                                            <SelectItem key={option.value} value={option.value}>
                                                {option.label}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>
                            <div className="flex justify-between items-start">
                                <span className="text-muted-alt">Assignee</span>
                                <div className="flex flex-col items-end gap-1">
                                    {user?.id != null &&
                                        !(assignee?.type === 'user' && String(assignee.id) === String(user.id)) && (
                                            <Button
                                                variant="default"
                                                size="xs"
                                                disabled={!!sendDisabledReason}
                                                title={sendDisabledReason ?? undefined}
                                                onClick={() => setAssignee({ type: 'user', id: user.id })}
                                            >
                                                <span className="text-accent">Assign to me</span>
                                            </Button>
                                        )}
                                    <AssigneeSelect
                                        assignee={assignee}
                                        onChange={setAssignee}
                                        disabledReason={sendDisabledReason}
                                    >
                                        {(resolvedAssignee, isOpen) => (
                                            <Button
                                                variant="outline"
                                                size="sm"
                                                aria-pressed={isOpen}
                                                disabled={!!sendDisabledReason}
                                                title={sendDisabledReason ?? undefined}
                                            >
                                                <span className="flex items-center gap-1">
                                                    <AssigneeIconDisplay assignee={resolvedAssignee} size="small" />
                                                    <AssigneeLabelDisplay assignee={resolvedAssignee} size="small" />
                                                </span>
                                                {sendDisabledReason ? null : <SelectTriggerIcon />}
                                            </Button>
                                        )}
                                    </AssigneeSelect>
                                </div>
                            </div>
                            {ticket?.sla_due_at && (
                                <div className="flex justify-between items-center">
                                    <span className="text-muted-alt">SLA</span>
                                    <SlaDisplay slaDueAt={ticket.sla_due_at} />
                                </div>
                            )}
                            <div className="flex justify-between items-center">
                                <span className="text-muted-alt">Snooze</span>
                                <TicketSnoozeButton
                                    snoozedUntil={snoozedUntil}
                                    disabledReason={sendDisabledReason}
                                    onChange={setSnoozedUntil}
                                    onApplyAndSetOnHold={(nextSnoozedUntil) => {
                                        setSnoozedUntil(nextSnoozedUntil)
                                        setStatus('on_hold')
                                    }}
                                />
                            </div>
                            <div className="flex justify-between items-start gap-2">
                                <span className="text-muted-alt shrink-0">Tags</span>
                                <TicketTags
                                    tags={tags}
                                    onChange={setTags}
                                    saving={false}
                                    disabledReason={sendDisabledReason}
                                />
                            </div>
                        </div>
                        <div className="mt-3 pt-3 border-t flex justify-end">
                            <AccessControlAction
                                resourceType={AccessControlResourceType.Ticket}
                                minAccessLevel={AccessControlLevel.Editor}
                                userAccessLevel={ticket?.user_access_level}
                            >
                                {({ disabled, disabledReason }) => (
                                    <Button
                                        variant="primary"
                                        size="sm"
                                        onClick={() => updateTicket()}
                                        loading={ticketUpdating}
                                        disabled={disabled || !hasUnsavedChanges || ticketUpdating}
                                        title={
                                            disabledReason ?? (!hasUnsavedChanges ? 'No changes to save' : undefined)
                                        }
                                    >
                                        Save changes
                                    </Button>
                                )}
                            </AccessControlAction>
                        </div>
                    </LemonCard>

                    {/* Related Groups Panel */}
                    {(person?.uuid || ticket?.organization_id) && (
                        <RelatedGroupsPanel
                            personUuid={person?.uuid}
                            organizationId={ticket?.organization_id}
                            organizationIdSource={ticket?.organization_id_source}
                        />
                    )}

                    {/* Staff Actions Panel */}
                    {user?.is_staff && ticket && <StaffActionsPanel />}

                    {/* AI Triage Panel */}
                    {aiSuggestionsEnabled && ticket && (
                        <AIPanel
                            aiTriage={ticket.ai_triage}
                            knowledgeGaps={knowledgeGaps}
                            knowledgeGapsLoading={knowledgeGapsLoading}
                            onDismissGap={dismissKnowledgeGap}
                        />
                    )}

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
                                personDistinctIds={person?.distinct_ids}
                            />
                        </>
                    )}

                    {/* Activity History Panel */}
                    {ticket?.id && <TicketActivityPanel ticketId={ticket.id} />}
                </div>
            </div>
        </SceneContent>
    )
}
