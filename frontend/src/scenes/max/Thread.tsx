import clsx from 'clsx'
import { BindLogic, useValues } from 'kea'
import React, { useCallback, useMemo, useState } from 'react'

import { IconChevronRight, IconWarning, IconWrench } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDivider, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'
import {
    ChatBubble,
    ChatBubbleContent,
    ChatMarker,
    ChatMarkerContent,
    ChatMessage,
    ChatMessageContent,
    Skeleton,
} from '@posthog/quill'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { cn } from 'lib/utils/css-classes'
import { sceneLogic } from 'scenes/sceneLogic'

import {
    AssistantMessage,
    AssistantToolCallMessage,
    TaskExecutionStatus as ExecutionStatus,
    FailureMessage,
    MultiQuestionForm,
} from '~/queries/schema/schema-assistant-messages'
import { PendingApproval, RecordingUniversalFilters } from '~/types'

import { RecordingsWidget } from 'products/posthog_ai/frontend/api/dataWidgets'
import {
    AGENT_TOOL_APPLY_BACK_CONTEXT_ITEM,
    getThinkingMessageFromResponse,
    runStreamLogic,
    useAttachedContext,
    useForegroundStream,
    useThreadSkin,
} from 'products/posthog_ai/frontend/api/logics'
import {
    AssistantFailureMessage,
    ContextUsageChip,
    MarkdownMessage,
    MessageTemplate,
    QuillAssistantBubble,
    QuillAssistantMarkdown,
    MessageReveal,
    NotQuill,
    QuillHumanBubble,
    QuillThreadSkin,
    ReasoningAnswer,
    ThreadView,
    TurnTrailerActions,
    type TurnTrailer,
    useQuillThread,
} from 'products/posthog_ai/frontend/api/primitives'
import { LogEntry } from 'products/posthog_ai/frontend/lib/parse-logs'
import { isPiTaskRuntime } from 'products/posthog_ai/frontend/types/taskTypes'
import { ReplayVisionScanWidget } from 'products/replay_vision/frontend/posthogAi/ReplayVisionScanWidget'

import { LangGraphActivity } from './components/Activity'
import { FeedbackDisplay } from './components/FeedbackDisplay'
import { ContextSummary } from './Context'
import { DangerousOperationApprovalCard } from './DangerousOperationApprovalCard'
import { FeedbackPrompt } from './FeedbackPrompt'
import { EnhancedToolCall, ToolRegistration, getToolDefinitionFromToolCall } from './max-constants'
import { maxGlobalLogic } from './maxGlobalLogic'
import { SIDE_PANEL_PANEL_ID, ThreadMessage, maxLogic } from './maxLogic'
import { maxThreadLogic } from './maxThreadLogic'
import { AssistantMessageForm } from './messages/AssistantMessageForm'
import { MultiQuestionFormRecap } from './messages/MultiQuestionForm'
import { MultiVisualizationAnswer } from './messages/MultiVisualizationAnswer'
import { NotebookArtifactAnswer } from './messages/NotebookArtifactAnswer'
import { PlanningAnswer } from './messages/PlanningAnswer'
import { RetriableFailureActions } from './messages/RetriableFailureActions'
import { SuccessActions } from './messages/SuccessActions'
import { isRenderableUIPayloadTool } from './messages/UIPayloadAnswer'
import { VisualizationArtifact } from './messages/VisualizationArtifact'
import { MAX_SLASH_COMMANDS, SlashCommandName } from './slash-commands'
import { TicketPrompt } from './TicketPrompt'
import { getTicketPromptData, getTicketSummaryData, isTicketConfirmationMessage } from './ticketUtils'
import { ToolCallWidgetDef, getToolCallDescriptionAndWidgetDef } from './toolCallDisplay'
import { TraceIdProvider } from './TraceIdContext'
import { useFeedback } from './useFeedback'
import {
    isArtifactMessage,
    isAssistantMessage,
    isAssistantToolCallMessage,
    isFailureMessage,
    isHumanMessage,
    isMultiQuestionFormMessage,
    isMultiVisualizationMessage,
    isNotebookArtifactContent,
    isVisualizationArtifactContent,
} from './utils'

// Helper function to check if a message is an error or failure
function isErrorMessage(message: ThreadMessage): boolean {
    return message.type !== 'human' && (message.status === 'error' || message.type === 'ai/failure')
}

/** A short assistant-side note (a feedback nudge, a retry notice): a lemon bubble, or quill ghost prose. */
function AssistantNote({
    children,
    boxClassName,
}: {
    children: React.ReactNode
    /** Lemon only: extra classes on the bubble's box. */
    boxClassName?: string
}): JSX.Element {
    const quill = useQuillThread()
    if (quill) {
        return <QuillAssistantBubble>{children}</QuillAssistantBubble>
    }
    return (
        <MessageTemplate type="ai" boxClassName={boxClassName}>
            {children}
        </MessageTemplate>
    )
}

export function Thread({ compact = false }: { compact?: boolean }): JSX.Element | null {
    const { conversation, sandboxConversationKey, isConvertedConversation } = useValues(maxThreadLogic)
    const { panelId } = useValues(maxLogic)
    const threadSkin = useThreadSkin()
    const quill = threadSkin === 'quill'
    const isSandboxRuntime = conversation?.agent_runtime === 'sandbox'
    const isPiTask = isPiTaskRuntime(conversation?.task?.runtime)

    // Register the sandbox stream rendered in the side panel as the foreground stream (tool apply-back
    // reacts only to it). Only the side-panel instance qualifies — the full-page /ai scene (any other
    // panelId) never registers. Cleared on unmount / conversation change via the streamKey dependency.
    const rendersSandboxThread = isSandboxRuntime || isConvertedConversation
    useForegroundStream(panelId === SIDE_PANEL_PANEL_ID && rendersSandboxThread ? sandboxConversationKey : null)

    // While the side panel shows a sandbox thread, tell the agent its tool calls are applied back into
    // whatever the user has open (the prompt-side half of the apply-back the foreground stream enables).
    useAttachedContext([AGENT_TOOL_APPLY_BACK_CONTEXT_ITEM], {
        active: panelId === SIDE_PANEL_PANEL_ID && rendersSandboxThread,
    })

    // The quill thread spaces its rows like PostHog Desktop, with the 2.0 thread's side gutter; the lemon
    // thread keeps its tighter rhythm.
    const containerClassName = cn(
        '@container/thread flex flex-col items-stretch w-full max-w-180 self-center grow mx-auto',
        quill ? 'gap-4 px-4' : 'gap-1.5',
        quill ? (compact ? 'py-1' : 'py-3') : compact ? 'p-1' : 'p-3'
    )

    // Feedback identity: always the task, matching `$ai_session_id` on other surfaces.
    const feedbackTaskId = conversation?.task?.id
    // Stable identity so the memoized trailer rows don't re-render on every streamed frame.
    const feedbackRun = useMemo(() => ({ taskId: feedbackTaskId }), [feedbackTaskId])
    const renderTurnTrailer = useCallback(
        (trailer: TurnTrailer): JSX.Element | null =>
            feedbackTaskId ? (
                <TurnTrailerActions trailer={trailer} sessionId={feedbackTaskId} run={feedbackRun} />
            ) : null,
        [feedbackTaskId, feedbackRun]
    )

    if (isPiTask) {
        return <LemonBanner type="info">Pi session logs aren't available in PostHog yet.</LemonBanner>
    }

    // Born-sandbox conversation (no legacy history): render only the sandbox thread.
    if (isSandboxRuntime && !isConvertedConversation) {
        if (!sandboxConversationKey) {
            return null
        }
        return (
            <div className={containerClassName}>
                {/* Same key maxThreadLogic's connect() uses, so both resolve the same instance */}
                <BindLogic
                    logic={runStreamLogic}
                    props={{ streamKey: sandboxConversationKey, conversationId: sandboxConversationKey }}
                >
                    {/* The live Max column owns scroll via ThreadAutoScroller — render rows in flow, not virtualized. */}
                    <ThreadView virtualized={false} renderTurnTrailer={renderTurnTrailer} skin={threadSkin} />
                </BindLogic>
            </div>
        )
    }

    // Converted conversation: the full legacy thread, a "history was converted" divider, then the
    // live sandbox thread — all in one scroll container so auto-scroll lands at the sandbox bottom.
    if (isConvertedConversation) {
        if (!sandboxConversationKey) {
            return null
        }
        const converted = (
            <>
                <LegacyThread showTrailers={false} />
                {quill ? (
                    <ChatMarker variant="separator" className="before:min-w-4 after:min-w-4">
                        <ChatMarkerContent className="max-w-[80%] shrink">
                            Message history was converted to the new format
                        </ChatMarkerContent>
                    </ChatMarker>
                ) : (
                    <LemonDivider dashed label="Message history was converted to the new format" className="my-3" />
                )}
                <BindLogic
                    logic={runStreamLogic}
                    props={{ streamKey: sandboxConversationKey, conversationId: sandboxConversationKey }}
                >
                    <ThreadView virtualized={false} renderTurnTrailer={renderTurnTrailer} skin={threadSkin} />
                </BindLogic>
            </>
        )
        return quill ? (
            <QuillThreadSkin className={containerClassName}>{converted}</QuillThreadSkin>
        ) : (
            <div className={containerClassName}>{converted}</div>
        )
    }

    // Pure LangGraph conversation.
    return quill ? (
        <QuillThreadSkin className={containerClassName}>
            <LegacyThread showTrailers />
        </QuillThreadSkin>
    ) : (
        <div className={containerClassName}>
            <LegacyThread showTrailers />
        </div>
    )
}

/**
 * LangGraph thread renderer: renders `maxThreadLogic.threadGrouped` (message history), loading
 * skeletons, or a NotFound fallback. `showTrailers` gates the feedback / ticket prompts so a
 * converted conversation renders them once at the true bottom (below the sandbox thread), not
 * wedged above the conversion divider.
 */
function LegacyThread({ showTrailers }: { showTrailers: boolean }): JSX.Element | null {
    const { conversationLoading, messagesLoading, conversationId } = useValues(maxLogic)
    const { threadGrouped, streamingActive, threadLoading, sandboxEntries, canCreateTicket } = useValues(maxThreadLogic)
    const sandboxModeEnabled = useFeatureFlag('PHAI_SANDBOX_MODE')
    const { isPromptVisible, isDetailedFeedbackVisible, isThankYouVisible, traceId } = useFeedback(conversationId)

    // Gated on eligibility so the create-ticket affordance never renders for orgs the support
    // panel would turn away — e.g. from an old conversation that contains a past /ticket summary.
    const ticketPromptData = useMemo(
        () => (canCreateTicket ? getTicketPromptData(threadGrouped, streamingActive) : { needed: false }),
        [threadGrouped, streamingActive, canCreateTicket]
    )

    const ticketSummaryData = useMemo(
        () => (canCreateTicket ? getTicketSummaryData(threadGrouped, streamingActive) : null),
        [threadGrouped, streamingActive, canCreateTicket]
    )

    const lastErrorIndex = useMemo(() => threadGrouped.findLastIndex(isErrorMessage), [threadGrouped])

    return (conversationLoading || messagesLoading) && threadGrouped.length === 0 ? (
        <>
            <MessageGroupSkeleton groupType="human" />
            <MessageGroupSkeleton groupType="ai" className="opacity-80" />
            <MessageGroupSkeleton groupType="human" className="opacity-65" />
            <MessageGroupSkeleton groupType="ai" className="opacity-40" />
            <MessageGroupSkeleton groupType="human" className="opacity-20" />
            <MessageGroupSkeleton groupType="ai" className="opacity-10" />
            <MessageGroupSkeleton groupType="human" className="opacity-5" />
        </>
    ) : threadGrouped.length > 0 ? (
        <>
            {(() => {
                // Track the current trace_id as we iterate forward through messages
                let currentTraceId: string | undefined

                return threadGrouped.map((message, index) => {
                    // Update trace_id when we encounter a human message
                    if (message.type === 'human' && 'trace_id' in message && message.trace_id) {
                        currentTraceId = message.trace_id
                    }

                    // Hide failed AI messages when retrying
                    if (threadLoading && isErrorMessage(message)) {
                        return null
                    }

                    // Hide old failed attempts - only show the most recent error
                    if (isErrorMessage(message) && index < lastErrorIndex) {
                        return null
                    }

                    // Hide duplicate human messages from retry pattern: Human → AI Error → Human (duplicate)
                    // This specific pattern only occurs when "Try again" is clicked after a failure
                    if (message.type === 'human' && 'content' in message && index >= 2) {
                        const prevMessage = threadGrouped[index - 1]
                        const prevPrevMessage = threadGrouped[index - 2]

                        const isRetryPattern =
                            isErrorMessage(prevMessage) &&
                            prevPrevMessage.type === 'human' &&
                            'content' in prevPrevMessage &&
                            prevPrevMessage.content === message.content

                        if (isRetryPattern) {
                            return null
                        }
                    }

                    // Hide UI payload answers that are not renderable to prevent rendering an empty message component
                    if (
                        isAssistantToolCallMessage(message) &&
                        (!message.ui_payload ||
                            !isRenderableUIPayloadTool(Object.keys(message.ui_payload)[0], message.ui_payload))
                    ) {
                        return null
                    }

                    const nextMessage = threadGrouped[index + 1]
                    const isLastInGroup = !nextMessage || (message.type === 'human') !== (nextMessage.type === 'human')

                    // Hiding rating buttons after /feedback and /ticket command outputs
                    const prevMessage = threadGrouped[index - 1]
                    const isSlashCommandResponse =
                        message.type !== 'human' &&
                        prevMessage?.type === 'human' &&
                        'content' in prevMessage &&
                        (prevMessage.content.startsWith(SlashCommandName.SlashFeedback) ||
                            prevMessage.content.startsWith(SlashCommandName.SlashTicket))

                    // Also hide for ticket confirmation messages
                    const isTicketConfirmation = isTicketConfirmationMessage(message)

                    // Check if this message is a ticket summary that needs the ticket creation button
                    const isTicketSummaryMessage = ticketSummaryData && ticketSummaryData.messageIndex === index

                    // For AI messages, use the current trace_id from the preceding human message
                    const messageTraceId = message.type !== 'human' ? currentTraceId : undefined

                    return (
                        <React.Fragment key={`${conversationId}-${index}`}>
                            <TraceIdProvider value={messageTraceId}>
                                <Message
                                    message={message}
                                    nextMessage={nextMessage}
                                    isLastInGroup={isLastInGroup}
                                    isFinal={index === threadGrouped.length - 1}
                                    isSlashCommandResponse={isSlashCommandResponse || isTicketConfirmation}
                                />
                            </TraceIdProvider>
                            {sandboxModeEnabled &&
                                sandboxEntries.length > 0 &&
                                isAssistantMessage(message) &&
                                message.id?.startsWith('sandbox-') &&
                                isLastInGroup && <SandboxActivityPanel entries={sandboxEntries} />}
                            {conversationId &&
                                isTicketSummaryMessage &&
                                (ticketSummaryData.discarded ? (
                                    <p className="m-0 ml-1 mt-1 text-xs text-muted italic">Ticket creation discarded</p>
                                ) : (
                                    <NotQuill>
                                        <TicketPrompt
                                            conversationId={conversationId}
                                            traceId={traceId}
                                            summary={ticketSummaryData.summary}
                                        />
                                    </NotQuill>
                                ))}
                        </React.Fragment>
                    )
                })
            })()}
            {showTrailers && conversationId && isPromptVisible && !streamingActive && (
                <AssistantNote>
                    <div className="flex flex-col gap-2">
                        <span className="text-xs text-muted">How is PostHog AI doing? (optional)</span>
                        <FeedbackDisplay conversationId={conversationId} />
                    </div>
                </AssistantNote>
            )}
            {showTrailers && conversationId && isDetailedFeedbackVisible && !streamingActive && (
                <NotQuill>
                    <FeedbackPrompt conversationId={conversationId} traceId={traceId} />
                </NotQuill>
            )}
            {showTrailers && conversationId && isThankYouVisible && !streamingActive && (
                <AssistantNote>
                    <p className="m-0 text-sm text-secondary">Thanks for your feedback and using PostHog AI!</p>
                </AssistantNote>
            )}
            {showTrailers && conversationId && ticketPromptData.needed && (
                <NotQuill>
                    <TicketPrompt
                        conversationId={conversationId}
                        traceId={traceId}
                        initialText={ticketPromptData.initialText}
                    />
                </NotQuill>
            )}
        </>
    ) : conversationId ? (
        <div className="flex flex-1 items-center justify-center">
            <NotFound object="conversation" className="m-0" />
        </div>
    ) : null
}

/**
 * Persistent sandbox surfaces mounted between the thread and the sticky composer: the
 * "PostHog resources used" bar and the context-usage indicator. Both read `runStreamLogic`
 * values directly, so this binds the same logic instance `Thread`'s sandbox path uses. Renders
 * nothing for non-sandbox conversations; the inner components hide themselves when empty.
 */
export function SandboxComposerSurfaces(): JSX.Element | null {
    const { conversation, sandboxConversationKey } = useValues(maxThreadLogic)
    const sandboxModeEnabled = useFeatureFlag('PHAI_SANDBOX_MODE')

    if (conversation?.agent_runtime !== 'sandbox' || !sandboxModeEnabled || !sandboxConversationKey) {
        return null
    }

    return (
        <BindLogic
            logic={runStreamLogic}
            props={{ streamKey: sandboxConversationKey, conversationId: sandboxConversationKey }}
        >
            <div className="w-full max-w-180 self-center mx-auto flex justify-end">
                <ContextUsageChip />
            </div>
        </BindLogic>
    )
}

function SandboxActivityPanel({ entries }: { entries: LogEntry[] }): JSX.Element | null {
    const [expanded, setExpanded] = useState(false)
    const toolEntries = entries.filter((e) => e.type === 'tool')
    const consoleEntries = entries.filter((e) => e.type === 'console')

    if (toolEntries.length === 0 && consoleEntries.length === 0) {
        return null
    }

    const summary = `${toolEntries.length} tool call${toolEntries.length !== 1 ? 's' : ''}${
        consoleEntries.length > 0 ? `, ${consoleEntries.length} log${consoleEntries.length !== 1 ? 's' : ''}` : ''
    }`

    return (
        <div className="ml-1 mt-1 mb-1">
            <LemonButton
                size="xsmall"
                type="secondary"
                icon={<IconWrench />}
                sideIcon={<IconChevronRight className={cn('transition-transform', expanded && 'rotate-90')} />}
                onClick={() => setExpanded(!expanded)}
            >
                <span className="text-xs text-muted">{summary}</span>
            </LemonButton>
            {expanded && (
                <div className="mt-1 ml-2 border-l-2 border-border pl-3 space-y-1 max-h-80 overflow-y-auto">
                    {toolEntries.map((entry) => (
                        <div key={entry.id} className="text-xs">
                            <span className="font-semibold">{entry.toolName}</span>
                            <span
                                className={cn(
                                    'ml-1.5',
                                    entry.toolStatus === 'completed'
                                        ? 'text-success'
                                        : entry.toolStatus === 'error'
                                          ? 'text-danger'
                                          : 'text-muted'
                                )}
                            >
                                {entry.toolStatus}
                            </span>
                        </div>
                    ))}
                    {consoleEntries.map((entry) => (
                        <div
                            key={entry.id}
                            className={cn(
                                'text-xs font-mono',
                                entry.level === 'error'
                                    ? 'text-danger'
                                    : entry.level === 'warn'
                                      ? 'text-warning'
                                      : 'text-muted'
                            )}
                        >
                            {entry.message}
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}

function MessageContainer({
    groupType,
    children,
    className,
}: {
    groupType: 'human' | 'ai'
    children: React.ReactNode
    className?: string
}): JSX.Element {
    const quill = useQuillThread()
    return (
        <div
            className={cn(
                'relative flex',
                // Off-screen messages (insight cards especially) otherwise participate in every
                // style recalc / layout / paint the composer triggers while typing, which makes
                // keystroke latency grow with thread length. `auto 100px` is only the pre-first-render
                // estimate; after a message renders once, the browser remembers its real size.
                '[content-visibility:auto] [contain-intrinsic-size:auto_100px]',
                // The quill bubbles align themselves and cap their own width, so the row stays full width.
                !quill && (groupType === 'human' ? 'flex-row-reverse ml-4 @md/thread:ml-10 ' : 'mr-4 @md/thread:mr-10'),
                className
            )}
        >
            {children}
        </div>
    )
}

interface MessageProps {
    message: ThreadMessage
    nextMessage?: ThreadMessage
    isLastInGroup: boolean
    isFinal: boolean
    isSlashCommandResponse?: boolean
}

// Memoized so a thread re-render (e.g. on every streaming token) only re-renders messages whose
// props actually changed. Relies on threadGrouped preserving message object identity for unchanged
// messages — see enhanceThreadToolCalls in maxThreadLogic.
const Message = React.memo(function Message({
    message,
    nextMessage,
    isLastInGroup,
    isFinal,
    isSlashCommandResponse,
}: MessageProps): JSX.Element | null {
    const { editInsightToolRegistered, registeredToolMap } = useValues(maxGlobalLogic)
    const { activeSceneId } = useValues(sceneLogic)
    const {
        threadLoading,
        isSharedThread,
        pendingApprovalsData,
        resolvedApprovalStatuses,
        webSearchResultsByToolUseId,
    } = useValues(maxThreadLogic)
    const { conversationId } = useValues(maxLogic)
    const quill = useQuillThread()

    const groupType = message.type === 'human' ? 'human' : 'ai'
    const key = message.id || 'no-id'

    // Compute resolved approval cards that match this message's tool_calls
    // Pending approvals are now shown in the input area, so we only show resolved ones here
    // Must be at component level (not inside conditional) to satisfy React hooks rules
    const approvalCardElements = useMemo(() => {
        if (!conversationId || !isAssistantMessage(message) || !message.tool_calls?.length) {
            return null
        }
        const toolCallIds = new Set(message.tool_calls.map((tc) => tc.id).filter(Boolean))
        // Show approvals that are resolved either by backend OR frontend
        // Backend: decision_status !== 'pending'
        // Frontend: resolvedApprovalStatuses[id] exists (for approvals resolved during this session)
        const matchingApprovals = (Object.values(pendingApprovalsData) as PendingApproval[]).filter(
            (approval) =>
                approval.original_tool_call_id &&
                toolCallIds.has(approval.original_tool_call_id) &&
                (approval.decision_status !== 'pending' || resolvedApprovalStatuses[approval.proposal_id])
        )
        if (matchingApprovals.length === 0) {
            return null
        }
        return matchingApprovals.map((approval) => (
            <NotQuill key={`approval-${approval.proposal_id}`}>
                <DangerousOperationApprovalCard
                    operation={{
                        status: 'pending_approval',
                        proposalId: approval.proposal_id,
                        toolName: approval.tool_name,
                        preview: approval.preview,
                        payload: approval.payload as Record<string, any>,
                    }}
                />
            </NotQuill>
        ))
    }, [conversationId, message, pendingApprovalsData, resolvedApprovalStatuses])

    // Skip rendering messages that produce no visible content.
    // This prevents empty MessageContainers from creating uneven gaps in the thread.
    const rendersContent =
        isHumanMessage(message) ||
        isAssistantMessage(message) ||
        isFailureMessage(message) ||
        (isAssistantToolCallMessage(message) &&
            message.ui_payload &&
            Object.values(message.ui_payload).filter((value) => value != null).length > 0) ||
        (isArtifactMessage(message) &&
            (isVisualizationArtifactContent(message.content) || isNotebookArtifactContent(message.content))) ||
        isMultiVisualizationMessage(message)

    if (!rendersContent && !(isLastInGroup && message.status === 'error')) {
        return null
    }
    return (
        <MessageContainer groupType={groupType}>
            <div className={clsx('flex flex-col min-w-0 w-full', groupType === 'human' ? 'items-end' : 'items-start')}>
                {(() => {
                    if (isHumanMessage(message)) {
                        const maybeCommand = MAX_SLASH_COMMANDS.find(
                            (cmd) => cmd.name === message.content.split(' ', 1)[0]
                        )
                        const contextSummary = message.ui_context && Object.keys(message.ui_context).length > 0 && (
                            <ContextSummary
                                insights={message.ui_context.insights}
                                dashboards={message.ui_context.dashboards}
                                events={message.ui_context.events}
                                actions={message.ui_context.actions}
                                notebooks={message.ui_context.notebooks}
                                useCurrentPageContext={false}
                            />
                        )
                        const humanContent = maybeCommand ? (
                            <div className="flex items-center">
                                <Tooltip
                                    title={
                                        <>
                                            This is a PostHog AI command:
                                            <br />
                                            <i>{maybeCommand.description}</i>
                                        </>
                                    }
                                >
                                    <span className="text-base mr-1.5">{maybeCommand.icon}</span>
                                </Tooltip>
                                <span className="font-mono">{message.content}</span>
                            </div>
                        ) : (
                            <MarkdownMessage content={message.content || '*No text.*'} id={message.id || 'no-text'} />
                        )

                        if (quill) {
                            return (
                                <MessageReveal key={key}>
                                    <QuillHumanBubble
                                        copyText={message.content || undefined}
                                        before={contextSummary || undefined}
                                        className={cn(
                                            'w-full',
                                            message.status === 'error' &&
                                                '[&_[data-slot=bubble-content]]:border-destructive-foreground'
                                        )}
                                    >
                                        {humanContent}
                                    </QuillHumanBubble>
                                </MessageReveal>
                            )
                        }

                        return (
                            <MessageTemplate
                                key={key}
                                type="human"
                                boxClassName={message.status === 'error' ? 'border-danger' : undefined}
                            >
                                {contextSummary}
                                {humanContent}
                            </MessageTemplate>
                        )
                    } else if (isAssistantMessage(message)) {
                        // Render thinking/reasoning if present
                        const hasContent = !!(
                            message.content.length > 0 ||
                            (message.tool_calls && message.tool_calls.length > 0)
                        )

                        let thinkingElements = null
                        const thinkingBlocks = getThinkingMessageFromResponse(message, webSearchResultsByToolUseId)
                        if (thinkingBlocks) {
                            // Thinking should be collapsed (show "Thought") if:
                            // 1. The thread has finished streaming (thinking might be at the end), OR
                            // 1. The message has content or tool_calls, OR
                            // 2. The message is not the last in group (there are subsequent messages)
                            // Otherwise, keep expanded to show active thinking progress
                            const isThinkingComplete = hasContent || !isLastInGroup || !threadLoading
                            thinkingElements = thinkingBlocks.map((block, index) =>
                                block.type === 'server_tool_use' ? (
                                    <ToolCallsAnswer
                                        key={`thinking-${index}`}
                                        toolCalls={[
                                            {
                                                type: 'tool_call',
                                                id: block.id,
                                                name: block.name,
                                                args: block.input,
                                                status: block.results
                                                    ? ExecutionStatus.Completed
                                                    : ExecutionStatus.InProgress,
                                                updates: block.results
                                                    ? block.results.map((result) => `[${result.title}](${result.url})`)
                                                    : [],
                                            },
                                        ]}
                                        registeredToolMap={registeredToolMap}
                                    />
                                ) : (
                                    <ReasoningAnswer
                                        key={`thinking-${index}`}
                                        content={block.thinking}
                                        id={message.id || key}
                                        completed={isThinkingComplete}
                                        showCompletionIcon={false}
                                    />
                                )
                            )
                        }

                        // Render tool calls if present (tool_calls are enhanced with status by threadGrouped selector)
                        const toolCallElements =
                            message.tool_calls && message.tool_calls.length > 0 ? (
                                <ToolCallsAnswer
                                    key={`${key}-tools`}
                                    toolCalls={message.tool_calls as EnhancedToolCall[]}
                                    registeredToolMap={registeredToolMap}
                                />
                            ) : null

                        // Allow action to be rendered in the middle if it has hrefs (like, links to open a report)
                        const ifActionInTheMiddle =
                            message.meta?.form?.options && message.meta.form.options.some((option) => option.href)
                        // Render main text content
                        const textElement = message.content ? (
                            <TextAnswer
                                key={`${key}-text`}
                                message={message}
                                withActions={ifActionInTheMiddle}
                                interactable={ifActionInTheMiddle}
                            />
                        ) : null

                        // Compute actions separately to render after tool calls
                        const retriable = !!(isLastInGroup && isFinal)
                        // Check if message has a multi-question form
                        // When isFinal is true, the form is shown in the input area, so don't render here
                        const multiQuestionFormElement = isMultiQuestionFormMessage(message)
                            ? (() => {
                                  if (message.status !== 'completed') {
                                      // Don't show streaming forms
                                      return null
                                  }
                                  // Don't show the form in the thread when it's the final pending form
                                  // because it's now displayed in the input area
                                  if (isFinal) {
                                      return null
                                  }
                                  const formArgs = message.tool_calls?.find(
                                      (toolCall) => toolCall.name === 'create_form'
                                  )?.args
                                  // Validate the form args have the expected structure
                                  if (!formArgs || !Array.isArray(formArgs.questions)) {
                                      return null
                                  }
                                  const form = formArgs as unknown as MultiQuestionForm
                                  const formResult =
                                      isAssistantToolCallMessage(nextMessage) && nextMessage.ui_payload?.create_form
                                          ? (nextMessage.ui_payload.create_form as {
                                                answers?: Record<string, string | string[]>
                                                status?: string
                                            })
                                          : undefined
                                  return (
                                      <MultiQuestionFormRecap
                                          key={`${key}-multi-form`}
                                          form={form}
                                          savedAnswers={formResult?.answers}
                                          formStatus={formResult?.status}
                                      />
                                  )
                              })()
                            : null

                        const actionsElement = (() => {
                            if (threadLoading) {
                                return null
                            }
                            if (message.status !== 'completed') {
                                return null
                            }
                            if (message.content.length === 0) {
                                return null
                            }

                            if (isLastInGroup) {
                                // When multi-question form is not final, hide actions (form is shown inline)
                                // When it IS final, the form is shown in the input area, so show actions here
                                if (isMultiQuestionFormMessage(message) && !isFinal) {
                                    return null
                                }
                                // Message has been interrupted with quick replies
                                // (non-links as ones with links get rendered in TextAnswer)
                                if (
                                    message.meta?.form?.options &&
                                    !message.meta?.form?.options.some((option) => option.href) &&
                                    isFinal
                                ) {
                                    return <AssistantMessageForm key={`${key}-form`} form={message.meta.form} />
                                }

                                // Show answer actions if the assistant's response is complete at this point
                                // For feedback command responses, only show the trace button (hide rating/retry)
                                return (
                                    <SuccessActions
                                        key={`${key}-actions`}
                                        retriable={retriable}
                                        hideRatingAndRetry={isSlashCommandResponse}
                                        content={message.content}
                                    />
                                )
                            }

                            return null
                        })()

                        return (
                            <div key={key} className="flex flex-col gap-1.5 w-full">
                                {thinkingElements}
                                {textElement}
                                {toolCallElements}
                                {approvalCardElements}
                                {multiQuestionFormElement}
                                {actionsElement}
                            </div>
                        )
                    } else if (isFailureMessage(message)) {
                        return (
                            <>
                                <TextAnswer
                                    key={key}
                                    message={message}
                                    interactable={!isSharedThread && isLastInGroup}
                                    isFinalGroup={isFinal}
                                />
                            </>
                        )
                    } else if (isArtifactMessage(message)) {
                        if (isVisualizationArtifactContent(message.content)) {
                            return (
                                // A chart card needs more room from the text around it than the thread's row gap gives.
                                <div key={key} className={quill ? 'my-2' : undefined}>
                                    <VisualizationArtifact
                                        message={message}
                                        content={message.content}
                                        status={message.status}
                                        isEditingInsight={editInsightToolRegistered}
                                        activeSceneId={activeSceneId}
                                    />
                                </div>
                            )
                        } else if (isNotebookArtifactContent(message.content)) {
                            return (
                                <NotQuill key={key} className="w-full">
                                    <NotebookArtifactAnswer
                                        content={message.content}
                                        status={message.status}
                                        artifactId={message.artifact_id}
                                    />
                                </NotQuill>
                            )
                        }
                        return null
                    } else if (isMultiVisualizationMessage(message)) {
                        return <MultiVisualizationAnswer key={key} message={message} />
                    }
                    return null // We currently skip other types of messages
                })()}
                {isLastInGroup && message.status === 'error' && (
                    <AssistantNote boxClassName="border-warning">
                        <div className="flex items-center gap-1.5">
                            <IconWarning className="text-xl text-warning" />
                            <i>
                                PostHog AI is generating this answer one more time because the previous attempt has
                                failed.
                            </i>
                        </div>
                    </AssistantNote>
                )}
            </div>
        </MessageContainer>
    )
})

function MessageGroupSkeleton({
    groupType,
    className,
}: {
    groupType: 'human' | 'ai'
    className?: string
}): JSX.Element {
    const quill = useQuillThread()
    if (quill) {
        return (
            <MessageContainer className={clsx('items-center', className)} groupType={groupType}>
                <Skeleton
                    className={cn('h-10 w-3/5 rounded-lg', groupType === 'human' ? 'ml-auto' : 'mr-auto')}
                    aria-label="Loading messages"
                />
            </MessageContainer>
        )
    }
    return (
        <MessageContainer className={clsx('items-center', className)} groupType={groupType}>
            <LemonSkeleton className="h-10 w-3/5 rounded-lg border" />
        </MessageContainer>
    )
}

interface TextAnswerProps {
    message: (AssistantMessage | FailureMessage | AssistantToolCallMessage) & ThreadMessage
    interactable?: boolean
    isFinalGroup?: boolean
    withActions?: boolean
}

const TextAnswer = React.forwardRef<HTMLDivElement, TextAnswerProps>(function TextAnswer(
    { message, interactable, isFinalGroup, withActions = true },
    ref
) {
    const quill = useQuillThread()
    const retriable = !!(interactable && isFinalGroup)

    const action = withActions
        ? (() => {
              if (message.status !== 'completed' && !isFailureMessage(message)) {
                  return null
              }

              // Don't show retry button when rate-limited
              if (
                  isFailureMessage(message) &&
                  !message.content?.includes('usage limit') && // Don't show retry button when rate-limited
                  retriable
              ) {
                  return <RetriableFailureActions />
              }

              if (isAssistantMessage(message) && interactable) {
                  // Message has been interrupted with a form
                  if (
                      message.meta?.form?.options &&
                      (isFinalGroup || message.meta.form.options.some((option) => option.href))
                  ) {
                      return <AssistantMessageForm form={message.meta.form} linksOnly={!isFinalGroup} />
                  }

                  // Show answer actions if the assistant's response is complete at this point
                  return <SuccessActions retriable={retriable} content={message.content} />
              }

              return null
          })()
        : null

    if (isFailureMessage(message)) {
        return (
            <AssistantFailureMessage id={message.id || 'error'} content={message.content} ref={ref} action={action} />
        )
    }

    if (quill) {
        return (
            <ChatMessage align="start" ref={ref} data-message-type="ai" className="w-full">
                <ChatMessageContent className="gap-1">
                    <ChatBubble
                        variant="ghost"
                        className={cn(
                            message.status === 'error' && '[&_[data-slot=bubble-content]]:border-destructive-foreground'
                        )}
                    >
                        <ChatBubbleContent>
                            <QuillAssistantMarkdown content={message.content || ''} id={message.id || 'in-progress'} />
                        </ChatBubbleContent>
                    </ChatBubble>
                    {action}
                </ChatMessageContent>
            </ChatMessage>
        )
    }

    return (
        <MessageTemplate
            type="ai"
            boxClassName={message.status === 'error' ? 'border-danger' : undefined}
            ref={ref}
            action={action}
        >
            <MarkdownMessage content={message.content || ''} id={message.id || 'in-progress'} />
        </MessageTemplate>
    )
})

interface ToolCallsAnswerProps {
    toolCalls: EnhancedToolCall[]
    registeredToolMap: Record<string, ToolRegistration>
}

function ToolCallsAnswer({ toolCalls, registeredToolMap }: ToolCallsAnswerProps): JSX.Element {
    const { onAcceptSessionFilters } = useValues(maxLogic)
    // Separate todo_write tool calls from regular tool calls
    const todoWriteToolCalls = toolCalls.filter((tc) => tc.name === 'todo_write')
    const regularToolCalls = toolCalls.filter((tc) => tc.name !== 'todo_write')

    return (
        <>
            {/* Render planning messages for todo_write tool calls */}
            {todoWriteToolCalls.map((toolCall) => {
                if (!toolCall.args.todos || (toolCall.args.todos as any[]).length === 0) {
                    return null
                }
                return (
                    <PlanningAnswer
                        key={toolCall.id}
                        toolCall={toolCall}
                        isLastPlanningMessage={toolCall.isLastPlanningMessage}
                    />
                )
            })}

            {/* Render tool execution for regular tool calls */}
            {regularToolCalls.length > 0 && (
                <div className="flex flex-col gap-1.5">
                    {regularToolCalls.map((toolCall) => {
                        const definition = getToolDefinitionFromToolCall(toolCall)
                        const [description, widgetDef] = getToolCallDescriptionAndWidgetDef(toolCall, registeredToolMap)
                        const widget = renderToolCallWidget(widgetDef, toolCall.id, onAcceptSessionFilters)
                        return (
                            <LangGraphActivity
                                key={toolCall.id}
                                id={toolCall.id}
                                content={description}
                                substeps={[]}
                                state={toolCall.status}
                                icon={definition?.icon || <IconWrench />}
                                showCompletionIcon={true}
                                widget={widget}
                                toolCall={toolCall}
                            />
                        )
                    })}
                </div>
            )}
        </>
    )
}

function renderToolCallWidget(
    widgetDef: ToolCallWidgetDef | null,
    toolCallId: string,
    onAcceptSessionFilters?: ((filters: RecordingUniversalFilters) => void) | null
): JSX.Element | null {
    switch (widgetDef?.widget) {
        case 'recordings':
            return (
                <RecordingsWidget
                    toolCallId={toolCallId}
                    filters={widgetDef.args}
                    embedded
                    onAcceptFilters={onAcceptSessionFilters}
                />
            )
        case 'replay_vision_scan':
            return (
                <ReplayVisionScanWidget
                    scanId={widgetDef.args.scanId}
                    sessionIds={widgetDef.args.sessionIds}
                    skipped={widgetDef.args.skipped}
                />
            )
        default:
            return null
    }
}
