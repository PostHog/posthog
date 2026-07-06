// Side-effect: registers Max's product-specific tool renderers (insight/dashboard/recordings/etc.) into
// the shared toolRegistry. Imported here so they're registered whenever the Max thread renders.
import './messages/adapters/registerMaxToolRenderers'

import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import React, { useLayoutEffect, useMemo, useState } from 'react'

import {
    IconChevronRight,
    IconCollapse,
    IconCopy,
    IconExpand,
    IconEye,
    IconHide,
    IconNotebook,
    IconRefresh,
    IconThumbsDown,
    IconThumbsDownFilled,
    IconThumbsUp,
    IconThumbsUpFilled,
    IconWarning,
    IconWrench,
    IconX,
} from '@posthog/icons'
import {
    LemonButton,
    LemonButtonPropsBase,
    LemonCheckbox,
    LemonDialog,
    LemonDivider,
    LemonInput,
    LemonSkeleton,
    Tooltip,
} from '@posthog/lemon-ui'

import {
    InsightBreakdownSummary,
    PropertiesSummary,
    SeriesSummary,
} from 'lib/components/Cards/InsightCard/InsightDetails'
import { TopHeading } from 'lib/components/Cards/InsightCard/TopHeading'
import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { cn } from 'lib/utils/css-classes'
import { pluralize } from 'lib/utils/strings'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { copyToClipboard } from '~/lib/utils/copyToClipboard'
import { stripMarkdown } from '~/lib/utils/markdown'
import { Query } from '~/queries/Query/Query'
import {
    AssistantForm,
    AssistantMessage,
    AssistantToolCallMessage,
    TaskExecutionStatus as ExecutionStatus,
    FailureMessage,
    MultiQuestionForm,
    MultiVisualizationMessage,
    PlanningStep,
    PlanningStepStatus,
} from '~/queries/schema/schema-assistant-messages'
import { DataVisualizationNode, InsightVizNode } from '~/queries/schema/schema-general'
import { isDataVisualizationNode, isHogQLQuery } from '~/queries/utils'
import { PendingApproval, Region } from '~/types'

import { getThinkingMessageFromResponse, runStreamLogic } from 'products/posthog_ai/frontend/api/logics'
import {
    AssistantFailureMessage,
    ContextUsageBar,
    MarkdownMessage,
    MessageTemplate,
    ReasoningAnswer,
    ResourcesBar,
    ThreadView,
} from 'products/posthog_ai/frontend/api/primitives'
import { LogEntry } from 'products/posthog_ai/frontend/lib/parse-logs'

import { LangGraphActivity, ShimmeringContent } from './components/Activity'
import { FeedbackDisplay } from './components/FeedbackDisplay'
import { MaxWebAnalyticsNudge } from './components/MaxWebAnalyticsNudge'
import { ContextSummary } from './Context'
import { DangerousOperationApprovalCard } from './DangerousOperationApprovalCard'
import { FeedbackPrompt } from './FeedbackPrompt'
import { maxMessageRatingsLogic } from './logics/maxMessageRatingsLogic'
import { EnhancedToolCall, ToolRegistration, getToolDefinitionFromToolCall } from './max-constants'
import { maxGlobalLogic } from './maxGlobalLogic'
import { ThreadMessage, maxLogic } from './maxLogic'
import { maxThreadLogic } from './maxThreadLogic'
import { MultiQuestionFormRecap } from './messages/MultiQuestionForm'
import { NotebookArtifactAnswer } from './messages/NotebookArtifactAnswer'
import { SessionSummarizationProgress } from './messages/SessionSummarizationProgress'
import { RecordingsWidget, isRenderableUIPayloadTool } from './messages/UIPayloadAnswer'
import { VisualizationArtifact } from './messages/VisualizationArtifact'
import { MAX_SLASH_COMMANDS, SlashCommandName } from './slash-commands'
import { TicketPrompt } from './TicketPrompt'
import { getTicketPromptData, getTicketSummaryData, isTicketConfirmationMessage } from './ticketUtils'
import { ToolCallWidgetDef, getToolCallDescriptionAndWidgetDef } from './toolCallDisplay'
import { TraceIdProvider, useTraceId } from './TraceIdContext'
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
    visualizationTypeToQuery,
} from './utils'

// Helper function to check if a message is an error or failure
function isErrorMessage(message: ThreadMessage): boolean {
    return message.type !== 'human' && (message.status === 'error' || message.type === 'ai/failure')
}

export function Thread({ className }: { className?: string }): JSX.Element | null {
    const { conversation, sandboxConversationKey, isConvertedConversation } = useValues(maxThreadLogic)
    const isSandboxRuntime = conversation?.agent_runtime === 'sandbox'

    const containerClassName = cn(
        '@container/thread flex flex-col items-stretch w-full max-w-180 self-center gap-1.5 grow mx-auto',
        className
    )

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
                    <ThreadView virtualized={false} />
                </BindLogic>
                <SandboxTicketSurface />
            </div>
        )
    }

    // Converted conversation: the full legacy thread, a "history was converted" divider, then the
    // live sandbox thread — all in one scroll container so auto-scroll lands at the sandbox bottom.
    if (isConvertedConversation) {
        if (!sandboxConversationKey) {
            return null
        }
        return (
            <div className={containerClassName}>
                <LegacyThread showTrailers={false} />
                <LemonDivider dashed label="Message history was converted to the new format" className="my-3" />
                <BindLogic
                    logic={runStreamLogic}
                    props={{ streamKey: sandboxConversationKey, conversationId: sandboxConversationKey }}
                >
                    <ThreadView virtualized={false} />
                </BindLogic>
                <SandboxTicketSurface />
            </div>
        )
    }

    // Pure LangGraph conversation.
    return (
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
    const { threadGrouped, streamingActive, threadLoading, sandboxEntries } = useValues(maxThreadLogic)
    const sandboxModeEnabled = useFeatureFlag('PHAI_SANDBOX_MODE')
    const { isPromptVisible, isDetailedFeedbackVisible, isThankYouVisible, traceId } = useFeedback(conversationId)

    const ticketPromptData = useMemo(
        () => getTicketPromptData(threadGrouped, streamingActive),
        [threadGrouped, streamingActive]
    )

    const ticketSummaryData = useMemo(
        () => getTicketSummaryData(threadGrouped, streamingActive),
        [threadGrouped, streamingActive]
    )

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
                    if (isErrorMessage(message)) {
                        const hasNewerError = threadGrouped.slice(index + 1).some(isErrorMessage)
                        if (hasNewerError) {
                            return null
                        }
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
                                    <TicketPrompt
                                        conversationId={conversationId}
                                        traceId={traceId}
                                        summary={ticketSummaryData.summary}
                                    />
                                ))}
                        </React.Fragment>
                    )
                })
            })()}
            {showTrailers && conversationId && isPromptVisible && !streamingActive && (
                <MessageTemplate type="ai">
                    <div className="flex flex-col gap-2">
                        <span className="text-xs text-muted">How is PostHog AI doing? (optional)</span>
                        <FeedbackDisplay conversationId={conversationId} />
                    </div>
                </MessageTemplate>
            )}
            {showTrailers && conversationId && isDetailedFeedbackVisible && !streamingActive && (
                <FeedbackPrompt conversationId={conversationId} traceId={traceId} />
            )}
            {showTrailers && conversationId && isThankYouVisible && !streamingActive && (
                <MessageTemplate type="ai">
                    <p className="m-0 text-sm text-secondary">Thanks for your feedback and using PostHog AI!</p>
                </MessageTemplate>
            )}
            {showTrailers && conversationId && ticketPromptData.needed && (
                <TicketPrompt
                    conversationId={conversationId}
                    traceId={traceId}
                    initialText={ticketPromptData.initialText}
                />
            )}
        </>
    ) : conversationId ? (
        <div className="flex flex-1 items-center justify-center">
            <NotFound object="conversation" className="m-0" />
        </div>
    ) : null
}

/**
 * The `/ticket` surface for the sandbox runtime, driven by the response-set `sandboxTicketSummary`
 * reducer (the LangGraph path scans `ThreadMessage`s via `ticketUtils` instead). `prompt` shows the
 * "describe your issue" input for a first-message ticket; `summary` shows the "Create support ticket"
 * button pre-filled with the AI summary. Renders below the sandbox thread in both sandbox branches.
 */
function SandboxTicketSurface(): JSX.Element | null {
    const { sandboxTicketSummary, conversationId, traceId } = useValues(maxThreadLogic)

    if (!sandboxTicketSummary || !conversationId) {
        return null
    }

    return (
        <TicketPrompt
            conversationId={conversationId}
            traceId={traceId}
            summary={sandboxTicketSummary.mode === 'summary' ? sandboxTicketSummary.summary : undefined}
            initialText={sandboxTicketSummary.mode === 'prompt' ? sandboxTicketSummary.initialText : undefined}
        />
    )
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
            <div className="w-full max-w-180 self-center mx-auto">
                <ResourcesBar />
                <ContextUsageBar />
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
    return (
        <div
            className={cn(
                'relative flex',
                groupType === 'human' ? 'flex-row-reverse ml-4 @md/thread:ml-10 ' : 'mr-4 @md/thread:mr-10',
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
    const { threadLoading, isSharedThread, pendingApprovalsData, resolvedApprovalStatuses } = useValues(maxThreadLogic)
    const { conversationId } = useValues(maxLogic)

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
            <DangerousOperationApprovalCard
                key={`approval-${approval.proposal_id}`}
                operation={{
                    status: 'pending_approval',
                    proposalId: approval.proposal_id,
                    toolName: approval.tool_name,
                    preview: approval.preview,
                    payload: approval.payload as Record<string, any>,
                }}
            />
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

                        return (
                            <MessageTemplate
                                key={key}
                                type="human"
                                boxClassName={message.status === 'error' ? 'border-danger' : undefined}
                            >
                                {message.ui_context && Object.keys(message.ui_context).length > 0 && (
                                    <ContextSummary
                                        insights={message.ui_context.insights}
                                        dashboards={message.ui_context.dashboards}
                                        events={message.ui_context.events}
                                        actions={message.ui_context.actions}
                                        notebooks={message.ui_context.notebooks}
                                        useCurrentPageContext={false}
                                    />
                                )}
                                {maybeCommand ? (
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
                                    <MarkdownMessage
                                        content={message.content || '*No text.*'}
                                        id={message.id || 'no-text'}
                                    />
                                )}
                            </MessageTemplate>
                        )
                    } else if (isAssistantMessage(message)) {
                        // Render thinking/reasoning if present
                        const hasContent = !!(
                            message.content.length > 0 ||
                            (message.tool_calls && message.tool_calls.length > 0)
                        )

                        let thinkingElements = null
                        const thinkingBlocks = getThinkingMessageFromResponse(message)
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
                                <VisualizationArtifact
                                    key={key}
                                    message={message}
                                    content={message.content}
                                    status={message.status}
                                    isEditingInsight={editInsightToolRegistered}
                                    activeSceneId={activeSceneId}
                                />
                            )
                        } else if (isNotebookArtifactContent(message.content)) {
                            return (
                                <NotebookArtifactAnswer
                                    key={key}
                                    content={message.content}
                                    status={message.status}
                                    artifactId={message.artifact_id}
                                />
                            )
                        }
                        return null
                    } else if (isMultiVisualizationMessage(message)) {
                        return <MultiVisualizationAnswer key={key} message={message} />
                    }
                    return null // We currently skip other types of messages
                })()}
                {isFinal &&
                    isLastInGroup &&
                    message.status === 'completed' &&
                    message.id &&
                    !message.id.startsWith('temp-') && (
                        <MaxWebAnalyticsNudge message={message} messageId={message.id} />
                    )}
                {isLastInGroup && message.status === 'error' && (
                    <MessageTemplate type="ai" boxClassName="border-warning">
                        <div className="flex items-center gap-1.5">
                            <IconWarning className="text-xl text-warning" />
                            <i>
                                PostHog AI is generating this answer one more time because the previous attempt has
                                failed.
                            </i>
                        </div>
                    </MessageTemplate>
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

interface AssistantMessageFormProps {
    form: AssistantForm
    linksOnly?: boolean
}

function AssistantMessageForm({ form, linksOnly }: AssistantMessageFormProps): JSX.Element {
    const { askMax } = useActions(maxThreadLogic)

    const options = linksOnly ? form.options.filter((option) => option.href) : form.options

    return (
        // ml-1 is because buttons have radius of 0.375rem, while messages of 0.65rem, where diff = 0.25rem
        // Also makes it clear the form is subservient to the message. *Harmony*
        <div className="flex flex-wrap gap-1.5 ml-1 mt-1">
            {options.map((option) => (
                <LemonButton
                    key={option.value}
                    onClick={!option.href ? () => askMax(option.value) : undefined}
                    to={option.href}
                    size="small"
                    targetBlank={!!option.href}
                    type={
                        option.variant && ['primary', 'secondary', 'tertiary'].includes(option.variant)
                            ? (option.variant as LemonButtonPropsBase['type'])
                            : 'secondary'
                    }
                >
                    {option.value}
                </LemonButton>
            ))}
        </div>
    )
}

interface PlanningAnswerProps {
    toolCall: EnhancedToolCall
    isLastPlanningMessage?: boolean
}

function PlanningAnswer({ toolCall, isLastPlanningMessage = true }: PlanningAnswerProps): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(isLastPlanningMessage)

    useLayoutEffect(() => {
        setIsExpanded(isLastPlanningMessage)
    }, [isLastPlanningMessage])

    // Extract planning steps from tool call args
    // Assuming args has a 'todos' field with array of {content: string, status: string, activeForm: string}
    const steps: PlanningStep[] = Array.isArray(toolCall.args.todos)
        ? (
              toolCall.args.todos as Array<{
                  content: string
                  status: string
                  activeForm: string
              }>
          ).map((todo) => ({
              description: todo.content,
              status: todo.status as PlanningStepStatus,
          }))
        : []

    const completedCount = steps.filter((step) => step.status === 'completed').length
    const totalCount = steps.length
    const hasMultipleSteps = steps.length > 1

    return (
        <div className="flex flex-col text-xs">
            <div
                className={clsx(
                    'flex items-center select-none',
                    !hasMultipleSteps ? 'cursor-default' : 'cursor-pointer'
                )}
                onClick={!hasMultipleSteps ? undefined : () => setIsExpanded(!isExpanded)}
                aria-label={!hasMultipleSteps ? undefined : isExpanded ? 'Collapse plan' : 'Expand plan'}
            >
                <div className="flex items-center justify-center size-5">
                    <IconNotebook />
                </div>
                <div className="flex items-center gap-1.5 flex-1 min-w-0">
                    <span>Planning</span>
                    <span className="text-muted">
                        ({completedCount}/{totalCount})
                    </span>
                    {hasMultipleSteps && (
                        <button className="cursor-pointer inline-flex items-center hover:opacity-70 transition-opacity flex-shrink-0">
                            <span className={`transform transition-transform ${isExpanded ? 'rotate-90' : ''}`}>
                                <IconChevronRight />
                            </span>
                        </button>
                    )}
                </div>
            </div>
            {isExpanded && (
                <div className="mt-1.5 space-y-1.5 border-l-2 border-border-secondary pl-3.5 ml-2">
                    {steps.map((step, index) => {
                        const isCompleted = step.status === 'completed'
                        const isInProgress = step.status === 'in_progress'

                        return (
                            <div key={index} className="flex items-start gap-2 animate-fade-in">
                                <span className="flex-shrink-0">
                                    <LemonCheckbox checked={isCompleted} disabled size="xsmall" />
                                </span>
                                <span
                                    className={clsx(
                                        'leading-relaxed',
                                        isCompleted && 'text-muted line-through',
                                        isInProgress && 'font-medium'
                                    )}
                                >
                                    {step.description}
                                    {isInProgress && (
                                        <ShimmeringContent>
                                            <span className="text-muted ml-1">(in progress)</span>
                                        </ShimmeringContent>
                                    )}
                                </span>
                            </div>
                        )
                    })}
                </div>
            )}
        </div>
    )
}

interface ToolCallsAnswerProps {
    toolCalls: EnhancedToolCall[]
    registeredToolMap: Record<string, ToolRegistration>
}

function ToolCallsAnswer({ toolCalls, registeredToolMap }: ToolCallsAnswerProps): JSX.Element {
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
                        const widget = renderToolCallWidget(widgetDef, toolCall.id)
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

const Visualization = React.memo(function Visualization({
    query,
    collapsed,
    editingChildren,
}: {
    query: InsightVizNode | DataVisualizationNode
    collapsed?: boolean
    editingChildren?: React.ReactNode
}): JSX.Element | null {
    const [isSummaryShown, setIsSummaryShown] = useState(false)
    const [isCollapsed, setIsCollapsed] = useState(collapsed ?? false)

    if (!query) {
        return null
    }

    return (
        <>
            {!isCollapsed && <Query query={query} readOnly embedded />}
            <div className={clsx('flex items-center justify-between', !isCollapsed && 'mt-2')}>
                <div className="flex items-center gap-1.5">
                    <LemonButton
                        sideIcon={isSummaryShown ? <IconCollapse /> : <IconExpand />}
                        onClick={() => setIsSummaryShown(!isSummaryShown)}
                        size="xsmall"
                        className="-m-1 shrink"
                        tooltip={isSummaryShown ? 'Hide definition' : 'Show definition'}
                    >
                        <h5 className="m-0 leading-none">
                            <TopHeading query={query} />
                        </h5>
                    </LemonButton>
                </div>
                <div className="flex items-center gap-1.5">
                    {editingChildren}
                    <LemonButton
                        icon={isCollapsed ? <IconEye /> : <IconHide />}
                        onClick={() => setIsCollapsed(!isCollapsed)}
                        size="xsmall"
                        className="-m-1 shrink"
                        tooltip={isCollapsed ? 'Show visualization' : 'Hide visualization'}
                    />
                </div>
            </div>
            {isSummaryShown && !isDataVisualizationNode(query) && (
                <>
                    <SeriesSummary query={query.source} heading={null} />
                    {!isHogQLQuery(query.source) && (
                        <div className="flex flex-wrap gap-4 mt-1 *:grow">
                            <PropertiesSummary properties={query.source.properties} />
                            <InsightBreakdownSummary query={query.source} />
                        </div>
                    )}
                </>
            )}
        </>
    )
})

interface MultiVisualizationAnswerProps {
    message: MultiVisualizationMessage
    className?: string
}

export function MultiVisualizationAnswer({ message, className }: MultiVisualizationAnswerProps): JSX.Element | null {
    const { visualizations } = message
    const insights = useMemo(() => {
        return visualizations
            .map((visualization, index) => {
                const query = visualizationTypeToQuery(visualization)
                if (query) {
                    return {
                        query,
                        title: visualization.plan || `Insight #${index + 1}`,
                    }
                }
                return null
            })
            .filter(Boolean) as Array<{
            query: InsightVizNode | DataVisualizationNode
            title: string
        }>
    }, [visualizations])

    const openModal = (): void => {
        LemonDialog.open({
            title: 'Insights',
            content: <MultiVisualizationModal insights={insights} />,
            primaryButton: null,
            width: '90%',
            maxWidth: 1400,
        })
    }

    if (visualizations.length === 0) {
        return null
    }

    // Render insights in a mosaic layout
    const renderMosaic = (): JSX.Element => {
        if (visualizations.length === 1) {
            // Single insight takes full width
            return (
                <div className="w-full relative">
                    <Visualization query={insights[0].query} />
                </div>
            )
        }
        // Two or more insights, show in a grid layout
        // Currently, let's show a maximum of 4 insights inline with the following mapping
        // 2 insights: 50/50 split
        // 3 insights: 33/33/33 split
        // 4 insights: 25/25/25/25 split, sso basically 2x2 grid
        const insightsToShow = insights.slice(0, 4)
        const gridCols =
            insightsToShow.length === 2 ? 'grid-cols-2' : insightsToShow.length === 3 ? 'grid-cols-3' : 'grid-cols-2'

        return (
            <div className={`grid ${gridCols} gap-2`}>
                {insightsToShow.map((insight, index) => (
                    <div key={index} className="relative min-h-[200px]">
                        <Query query={insight.query} readOnly embedded />
                    </div>
                ))}
            </div>
        )
    }

    return (
        <div className={clsx('flex flex-col gap-px w-full break-words', className)}>
            {/* Everything wrapped in a message bubble */}
            <div className="max-w-full border py-3 px-4 rounded-lg bg-surface-primary">
                <div className="space-y-2">
                    <div className="w-full flex justify-between items-center">
                        <h2 className="text-sm font-semibold text-secondary">
                            {pluralize(visualizations.length, 'insight')} analyzed
                        </h2>

                        {visualizations.length > 1 && (
                            <LemonButton
                                icon={<IconExpand />}
                                size="xsmall"
                                type="tertiary"
                                onClick={openModal}
                                tooltip="View all insights in detail"
                            >
                                Expand
                            </LemonButton>
                        )}
                    </div>

                    {renderMosaic()}

                    {message.commentary && <MarkdownMessage content={message.commentary} id="multi-viz-commentary" />}
                </div>
            </div>
        </div>
    )
}

// Modal for detailed view
interface MultiVisualizationModalProps {
    insights: Array<{
        query: InsightVizNode | DataVisualizationNode
        title: string
    }>
}

function MultiVisualizationModal({ insights: messages }: MultiVisualizationModalProps): JSX.Element {
    const [selectedIndex, setSelectedIndex] = React.useState(0)

    return (
        <div className="flex">
            {/* Sidebar with visualization list */}
            <div className="w-64 border-r pr-4 overflow-y-auto">
                <h5 className="text-xs font-semibold text-muted mb-3">VISUALIZATIONS</h5>
                <div className="space-y-1">
                    {messages.map((item, index) => (
                        <button
                            key={index}
                            onClick={() => setSelectedIndex(index)}
                            className={clsx(
                                'w-full text-left p-2 rounded transition-colors text-sm',
                                selectedIndex === index
                                    ? 'bg-primary text-primary-inverted font-semibold'
                                    : 'hover:bg-surface-secondary'
                            )}
                        >
                            {item.title}
                        </button>
                    ))}
                </div>
            </div>

            {/* Main content area */}
            <div className="flex-1 pl-4 overflow-auto">
                {messages[selectedIndex] && (
                    <>
                        <h4 className="text-base font-semibold mb-3">
                            <TopHeading query={messages[selectedIndex].query} />
                        </h4>
                        <div className="min-h-80">
                            <Query query={messages[selectedIndex].query} readOnly embedded />
                        </div>
                    </>
                )}
            </div>
        </div>
    )
}

function RetriableFailureActions(): JSX.Element {
    const { retryLastMessage } = useActions(maxThreadLogic)

    return (
        <LemonButton
            icon={<IconRefresh />}
            type="tertiary"
            size="xsmall"
            tooltip="Try again"
            onClick={() => retryLastMessage()}
            className="ml-1"
        >
            Try again
        </LemonButton>
    )
}

function SuccessActions({
    retriable,
    hideRatingAndRetry,
    content,
}: {
    retriable: boolean
    hideRatingAndRetry?: boolean
    content?: string | null
}): JSX.Element {
    const { traceId: logicTraceId } = useValues(maxThreadLogic)
    const { ratingForTraceId } = useValues(maxMessageRatingsLogic)
    const { setRatingForTraceId } = useActions(maxMessageRatingsLogic)
    const { retryLastMessage } = useActions(maxThreadLogic)
    const { user } = useValues(userLogic)
    const { isDev, preflight } = useValues(preflightLogic)
    const contextTraceId = useTraceId()

    // Use the context trace_id if available (for reloaded conversations), otherwise fall back to logic's traceId
    const traceId = contextTraceId || logicTraceId

    const rating = ratingForTraceId(traceId)
    const [feedback, setFeedback] = useState<string>('')
    const [feedbackInputStatus, setFeedbackInputStatus] = useState<'hidden' | 'pending' | 'submitted'>('hidden')

    function submitRating(newRating: 'good' | 'bad'): void {
        if (rating || !traceId) {
            return // Already rated
        }
        setRatingForTraceId({ traceId, rating: newRating })
        posthog.captureTraceMetric(traceId, 'quality', newRating)
        if (newRating === 'bad') {
            setFeedbackInputStatus('pending')
        }
    }

    function submitFeedback(): void {
        if (!feedback || !traceId) {
            return // Input is empty
        }
        posthog.captureTraceFeedback(traceId, feedback)
        setFeedbackInputStatus('submitted')
    }

    return (
        <>
            <div className="flex items-center ml-1">
                {content && (
                    <LemonButton
                        icon={<IconCopy />}
                        type="tertiary"
                        size="xsmall"
                        tooltip="Copy answer"
                        onClick={() => copyToClipboard(stripMarkdown(content))}
                    />
                )}
                {!hideRatingAndRetry && rating !== 'bad' && (
                    <LemonButton
                        icon={rating === 'good' ? <IconThumbsUpFilled /> : <IconThumbsUp />}
                        type="tertiary"
                        size="xsmall"
                        tooltip="Good answer"
                        onClick={() => submitRating('good')}
                    />
                )}
                {!hideRatingAndRetry && rating !== 'good' && (
                    <LemonButton
                        icon={rating === 'bad' ? <IconThumbsDownFilled /> : <IconThumbsDown />}
                        type="tertiary"
                        size="xsmall"
                        tooltip="Bad answer"
                        onClick={() => submitRating('bad')}
                    />
                )}
                {!hideRatingAndRetry && retriable && (
                    <LemonButton
                        icon={<IconRefresh />}
                        type="tertiary"
                        size="xsmall"
                        tooltip="Try again"
                        onClick={() => retryLastMessage()}
                    />
                )}
                {(user?.is_staff || isDev) && traceId && (
                    <LemonButton
                        to={`${preflight?.region === Region.EU ? 'https://us.posthog.com/project/2' : ''}${urls.aiObservabilityTrace(traceId)}`}
                        icon={<IconEye />}
                        type="tertiary"
                        size="xsmall"
                        tooltip="View trace in AI observability"
                    />
                )}
            </div>
            {!hideRatingAndRetry && feedbackInputStatus !== 'hidden' && (
                <MessageTemplate type="ai">
                    <div className="flex items-center gap-1">
                        <h4 className="m-0 text-sm grow">
                            {feedbackInputStatus === 'pending'
                                ? 'What disappointed you about the answer?'
                                : 'Thank you for your feedback!'}
                        </h4>
                        <LemonButton
                            icon={<IconX />}
                            type="tertiary"
                            size="xsmall"
                            onClick={() => {
                                setFeedbackInputStatus('hidden')
                            }}
                        />
                    </div>
                    {feedbackInputStatus === 'pending' && (
                        <div className="flex w-full gap-1.5 items-center mt-1.5">
                            <LemonInput
                                placeholder="Help us improve PostHog AI…"
                                fullWidth
                                value={feedback}
                                onChange={(newValue) => setFeedback(newValue)}
                                onPressEnter={() => submitFeedback()}
                                autoFocus
                            />
                            <LemonButton
                                type="primary"
                                onClick={() => submitFeedback()}
                                disabledReason={!feedback ? 'Please type a few words!' : undefined}
                            >
                                Submit
                            </LemonButton>
                        </div>
                    )}
                </MessageTemplate>
            )}
        </>
    )
}

function renderToolCallWidget(widgetDef: ToolCallWidgetDef | null, toolCallId: string): JSX.Element | null {
    switch (widgetDef?.widget) {
        case 'recordings':
            return <RecordingsWidget toolCallId={toolCallId} filters={widgetDef.args} embedded />
        case 'session_summarization':
            return <SessionSummarizationProgress updates={widgetDef.args.updates} />
        default:
            return null
    }
}
