import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import React, { useLayoutEffect, useMemo, useState } from 'react'
import { twMerge } from 'tailwind-merge'

import {
    IconBrain,
    IconCheck,
    IconChevronRight,
    IconCollapse,
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
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { pluralize } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { NotebookTarget } from 'scenes/notebooks/types'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { openNotebook } from '~/models/notebooksModel'
import { Query } from '~/queries/Query/Query'
import {
    AssistantForm,
    AssistantMessage,
    AssistantToolCall,
    AssistantToolCallMessage,
    TaskExecutionStatus as ExecutionStatus,
    FailureMessage,
    MultiVisualizationMessage,
    NotebookUpdateMessage,
    PlanningStep,
    PlanningStepStatus,
    VisualizationItem,
    VisualizationMessage,
} from '~/queries/schema/schema-assistant-messages'
import { DataVisualizationNode, InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { isFunnelsQuery, isHogQLQuery } from '~/queries/utils'
import { InsightShortId } from '~/types'

import { ContextSummary } from './Context'
import { MarkdownMessage } from './MarkdownMessage'
import { getToolDefinition } from './max-constants'
import { maxGlobalLogic } from './maxGlobalLogic'
import { MessageStatus, ThreadMessage, maxLogic } from './maxLogic'
import { maxThreadLogic } from './maxThreadLogic'
import { MAX_SLASH_COMMANDS } from './slash-commands'
import {
    castAssistantQuery,
    isAssistantMessage,
    isAssistantToolCallMessage,
    isDeepResearchReportCompletion,
    isFailureMessage,
    isHumanMessage,
    isMultiVisualizationMessage,
    isNotebookUpdateMessage,
    isVisualizationMessage,
} from './utils'
import { getThinkingMessageFromResponse } from './utils/thinkingMessages'

export function Thread({ className }: { className?: string }): JSX.Element | null {
    const { conversationLoading, conversationId } = useValues(maxLogic)
    const { threadGrouped, streamingActive } = useValues(maxThreadLogic)

    return (
        <div
            className={twMerge(
                '@container/thread flex flex-col items-stretch w-full max-w-180 self-center gap-1.5 grow mx-auto',
                className
            )}
        >
            {conversationLoading ? (
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
                threadGrouped.map((message, index) => {
                    const nextMessage = threadGrouped[index + 1]
                    const isLastInGroup = !nextMessage || (message.type === 'human') !== (nextMessage.type === 'human')

                    return (
                        <Message
                            key={`${conversationId}-${index}`}
                            message={message}
                            isLastInGroup={isLastInGroup}
                            isFinal={index === threadGrouped.length - 1}
                            streamingActive={streamingActive}
                        />
                    )
                })
            ) : (
                conversationId && (
                    <div className="flex flex-1 items-center justify-center">
                        <NotFound object="conversation" className="m-0" />
                    </div>
                )
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
            className={twMerge(
                'relative flex',
                groupType === 'human' ? 'flex-row-reverse ml-4 @md/thread:ml-10 ' : 'mr-4 @md/thread:mr-10',
                className
            )}
        >
            {children}
        </div>
    )
}

// Enhanced tool call with completion status and planning flag
export interface EnhancedToolCall extends AssistantToolCall {
    status: ExecutionStatus
    isLastPlanningMessage?: boolean
    updates?: string[]
}

interface MessageProps {
    message: ThreadMessage
    isLastInGroup: boolean
    isFinal: boolean
    streamingActive: boolean
}

function Message({ message, isLastInGroup, isFinal }: MessageProps): JSX.Element {
    const { editInsightToolRegistered } = useValues(maxGlobalLogic)
    const { activeTabId, activeSceneId } = useValues(sceneLogic)
    const { threadLoading } = useValues(maxThreadLogic)

    const groupType = message.type === 'human' ? 'human' : 'ai'
    const key = message.id || 'no-id'

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
                            const isThinkingComplete = !threadLoading || hasContent || !isLastInGroup
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
                        const toolCallElements = message.tool_calls?.length ? (
                            <ToolCallsAnswer
                                key={`${key}-tools`}
                                toolCalls={message.tool_calls as EnhancedToolCall[]}
                            />
                        ) : null

                        // Render main text content
                        const textElement = message.content ? (
                            <TextAnswer key={`${key}-text`} message={message} withActions={false} />
                        ) : null

                        // Compute actions separately to render after tool calls
                        const retriable = !!(isLastInGroup && isFinal)
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
                                // Message has been interrupted with a form
                                if (message.meta?.form?.options && isFinal) {
                                    return <AssistantMessageForm key={`${key}-form`} form={message.meta.form} />
                                }

                                // Show answer actions if the assistant's response is complete at this point
                                return <SuccessActions key={`${key}-actions`} retriable={retriable} />
                            }

                            return null
                        })()

                        return (
                            <div key={key} className="flex flex-col gap-1.5">
                                {thinkingElements}
                                {textElement}
                                {toolCallElements}
                                {actionsElement}
                            </div>
                        )
                    } else if (isAssistantToolCallMessage(message) || isFailureMessage(message)) {
                        return (
                            <TextAnswer
                                key={key}
                                message={message}
                                interactable={isLastInGroup}
                                isFinalGroup={isFinal}
                            />
                        )
                    } else if (isVisualizationMessage(message)) {
                        return (
                            <VisualizationAnswer
                                key={key}
                                message={message}
                                status={message.status}
                                isEditingInsight={editInsightToolRegistered}
                                activeTabId={activeTabId}
                                activeSceneId={activeSceneId}
                            />
                        )
                    } else if (isMultiVisualizationMessage(message)) {
                        return <MultiVisualizationAnswer key={key} message={message} />
                    } else if (isNotebookUpdateMessage(message)) {
                        return <NotebookUpdateAnswer key={key} message={message} />
                    }
                    return null // We currently skip other types of messages
                })()}
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
}

function MessageGroupSkeleton({
    groupType,
    className,
}: {
    groupType: 'human' | 'ai'
    className?: string
}): JSX.Element {
    return (
        <MessageContainer className={clsx('items-center', className)} groupType={groupType}>
            <LemonSkeleton className="w-8 h-8 rounded-full hidden border @md/thread:flex" />
            <LemonSkeleton className="h-10 w-3/5 rounded-lg border" />
        </MessageContainer>
    )
}

interface MessageTemplateProps {
    type: 'human' | 'ai'
    action?: React.ReactNode
    className?: string
    boxClassName?: string
    wrapperClassName?: string
    children?: React.ReactNode
    header?: React.ReactNode
}

const MessageTemplate = React.forwardRef<HTMLDivElement, MessageTemplateProps>(function MessageTemplate(
    { type, children, className, boxClassName, wrapperClassName, action, header },
    ref
) {
    return (
        <div
            className={twMerge(
                'flex flex-col gap-px w-full break-words scroll-mt-12',
                type === 'human' ? 'items-end' : 'items-start',
                className
            )}
            ref={ref}
        >
            <div className={twMerge('max-w-full', wrapperClassName)}>
                {header}
                {children && (
                    <div
                        className={twMerge(
                            'border py-2 px-3 rounded-lg bg-surface-primary',
                            type === 'human' && 'font-medium',
                            boxClassName
                        )}
                    >
                        {children}
                    </div>
                )}
            </div>
            {action}
        </div>
    )
})

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
                  if (message.meta?.form?.options && isFinalGroup) {
                      return <AssistantMessageForm form={message.meta.form} />
                  }

                  // Show answer actions if the assistant's response is complete at this point
                  return <SuccessActions retriable={retriable} />
              }

              return null
          })()
        : null

    return (
        <MessageTemplate
            type="ai"
            boxClassName={message.status === 'error' || message.type === 'ai/failure' ? 'border-danger' : undefined}
            ref={ref}
            action={action}
        >
            {message.content ? (
                <MarkdownMessage content={message.content} id={message.id || 'in-progress'} />
            ) : (
                <MarkdownMessage
                    content={message.content || '*PostHog AI has failed to generate an answer. Please try again.*'}
                    id={message.id || 'error'}
                />
            )}
        </MessageTemplate>
    )
})

interface AssistantMessageFormProps {
    form: AssistantForm
}

function AssistantMessageForm({ form }: AssistantMessageFormProps): JSX.Element {
    const { askMax } = useActions(maxThreadLogic)
    return (
        <div className="flex flex-wrap gap-1.5 mt-1">
            {form.options.map((option) => (
                <LemonButton
                    key={option.value}
                    onClick={() => askMax(option.value)}
                    size="small"
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

interface NotebookUpdateAnswerProps {
    message: NotebookUpdateMessage
}

function NotebookUpdateAnswer({ message }: NotebookUpdateAnswerProps): JSX.Element {
    const handleOpenNotebook = (notebookId?: string): void => {
        openNotebook(notebookId || message.notebook_id, NotebookTarget.Scene)
    }

    // Only show the full notebook list if this is the final report message from deep research
    const isReportCompletion = isDeepResearchReportCompletion(message)

    const NOTEBOOK_TYPE_DISPLAY_NAMES: Record<string, string> = {
        planning: 'Planning',
        report: 'Final Report',
    }

    const NOTEBOOK_TYPE_DESCRIPTIONS: Record<string, string> = {
        planning: 'Initial research plan and objectives',
        report: 'Comprehensive analysis and findings',
    }

    if (isReportCompletion && message.conversation_notebooks) {
        return (
            <MessageTemplate type="ai">
                <div className="bg-bg-light border border-border rounded-lg p-4 space-y-3">
                    <div className="flex items-center gap-2">
                        <IconCheck className="text-success size-4" />
                        <h4 className="text-sm font-semibold m-0">Deep Research Complete</h4>
                    </div>

                    <div className="space-y-2">
                        <p className="text-xs text-muted mb-3">
                            Your research has been completed. Each notebook contains detailed analysis:
                        </p>

                        {message.conversation_notebooks.map((notebook) => {
                            const typeKey = (notebook.notebook_type ??
                                'general') as keyof typeof NOTEBOOK_TYPE_DISPLAY_NAMES
                            const displayName = NOTEBOOK_TYPE_DISPLAY_NAMES[typeKey] || notebook.notebook_type
                            const description = NOTEBOOK_TYPE_DESCRIPTIONS[typeKey] || 'Research documentation'

                            return (
                                <div
                                    key={notebook.notebook_id}
                                    className="flex items-center justify-between p-3 bg-bg-3000 rounded border border-border-light"
                                >
                                    <div className="flex items-start gap-3">
                                        <IconNotebook className="size-4 text-primary-alt mt-0.5" />
                                        <div>
                                            <div className="flex items-center gap-2">
                                                <span className="font-medium text-sm">
                                                    {notebook.title || `${displayName} Notebook`}
                                                </span>
                                            </div>
                                            <div className="text-xs text-muted">{description}</div>
                                        </div>
                                    </div>
                                    <LemonButton
                                        onClick={() => handleOpenNotebook(notebook.notebook_id)}
                                        size="xsmall"
                                        type="primary"
                                        icon={<IconOpenInNew />}
                                    >
                                        Open
                                    </LemonButton>
                                </div>
                            )
                        })}
                    </div>
                </div>
            </MessageTemplate>
        )
    }

    // Default single notebook update message
    return (
        <MessageTemplate type="ai">
            <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                    <IconCheck className="text-success size-4" />
                    <span>A notebook has been updated</span>
                </div>
                <LemonButton onClick={() => handleOpenNotebook()} size="xsmall" type="primary" icon={<IconOpenInNew />}>
                    Open notebook
                </LemonButton>
            </div>
        </MessageTemplate>
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
        ? (toolCall.args.todos as Array<{ content: string; status: string; activeForm: string }>).map((todo) => ({
              description: todo.content,
              status: todo.status as PlanningStepStatus,
          }))
        : []

    const completedCount = steps.filter((step) => step.status === 'completed').length
    const totalCount = steps.length
    const hasMultipleSteps = steps.length > 1

    return (
        <div className="flex flex-col">
            <div
                className={clsx('flex items-center', !hasMultipleSteps ? 'cursor-default' : 'cursor-pointer')}
                onClick={!hasMultipleSteps ? undefined : () => setIsExpanded(!isExpanded)}
                aria-label={!hasMultipleSteps ? undefined : isExpanded ? 'Collapse plan' : 'Expand plan'}
            >
                <div className="relative flex-shrink-0 flex items-start justify-center size-6 h-full">
                    <div className="p-1 flex items-center justify-center">
                        <IconNotebook />
                    </div>
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
                <div className="mt-1.5 space-y-1.5 border-l-2 border-border-secondary pl-3.5 ml-[calc(0.775rem)]">
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
                                    {isInProgress && <span className="text-muted ml-1">(in progress)</span>}
                                </span>
                            </div>
                        )
                    })}
                </div>
            )}
        </div>
    )
}

function ShimmeringContent({ children }: { children: React.ReactNode }): JSX.Element {
    const isTextContent = typeof children === 'string'

    if (isTextContent) {
        return (
            <span
                className="bg-clip-text text-transparent"
                style={{
                    backgroundImage:
                        'linear-gradient(in oklch 90deg, var(--text-3000), var(--muted-3000), var(--trace-3000), var(--muted-3000), var(--text-3000))',
                    backgroundSize: '200% 100%',
                    animation: 'shimmer 3s linear infinite',
                }}
            >
                {children}
            </span>
        )
    }

    return (
        <span
            className="inline-flex"
            style={{
                animation: 'shimmer-opacity 3s linear infinite',
            }}
        >
            {children}
        </span>
    )
}

function handleThreeDots(content: string, isInProgress: boolean): string {
    if (!content.endsWith('...') && !content.endsWith('…') && !content.endsWith('.') && isInProgress) {
        return content + '...'
    } else if ((content.endsWith('...') || content.endsWith('…')) && !isInProgress) {
        return content.replace(/[…]/g, '').replace(/[.]/g, '')
    }
    return content
}

function AssistantActionComponent({
    id,
    content,
    substeps,
    state,
    icon,
    animate = true,
    showCompletionIcon = true,
}: {
    id: string
    content: string
    substeps: string[]
    state: ExecutionStatus
    icon?: React.ReactNode
    animate?: boolean
    showCompletionIcon?: boolean
}): JSX.Element {
    const isPending = state === 'pending'
    const isCompleted = state === 'completed'
    const isInProgress = state === 'in_progress'
    const isFailed = state === 'failed'
    const showChevron = substeps.length > 0 ? (showCompletionIcon ? isPending || isInProgress : true) : false
    // Initialize with the same logic as the effect to prevent flickering
    const [isExpanded, setIsExpanded] = useState(showChevron && !(isCompleted || isFailed))

    useLayoutEffect(() => {
        setIsExpanded(showChevron && !(isCompleted || isFailed))
    }, [showChevron, isCompleted, isFailed])

    let markdownContent = <MarkdownMessage id={id} content={content} />

    return (
        <div className="flex flex-col rounded transition-all duration-500 flex-1 min-w-0 gap-1 cursor-default">
            <div
                className={clsx(
                    'transition-all duration-500 flex',
                    (isPending || isFailed) && 'text-muted',
                    !isInProgress && !isPending && !isFailed && 'text-default',
                    !showChevron ? 'cursor-default' : 'cursor-pointer'
                )}
                onClick={!showChevron ? undefined : () => setIsExpanded(!isExpanded)}
                aria-label={!showChevron ? undefined : isExpanded ? 'Collapse history' : 'Expand history'}
            >
                {icon && (
                    <div className="flex items-center justify-center size-6">
                        {isInProgress && animate ? (
                            <ShimmeringContent>{icon}</ShimmeringContent>
                        ) : (
                            <span className="inline-flex">{icon}</span>
                        )}
                    </div>
                )}
                <div className="flex items-center gap-1 flex-1 min-w-0 h-full">
                    <div>
                        {isInProgress && animate ? (
                            <ShimmeringContent>{markdownContent}</ShimmeringContent>
                        ) : (
                            markdownContent
                        )}
                    </div>
                    {isCompleted && showCompletionIcon && <IconCheck className="text-success size-3" />}
                    {isFailed && showCompletionIcon && <IconX className="text-danger size-3" />}
                    {showChevron && (
                        <div className="relative flex-shrink-0 flex items-start justify-center h-full pt-px">
                            <button className="inline-flex items-center hover:opacity-70 transition-opacity flex-shrink-0 cursor-pointer">
                                <span className={clsx('transform transition-transform', isExpanded && 'rotate-90')}>
                                    <IconChevronRight />
                                </span>
                            </button>
                        </div>
                    )}
                </div>
            </div>
            {isExpanded && substeps && substeps.length > 0 && (
                <div
                    className={clsx(
                        'space-y-1 border-l-2 border-border-secondary',
                        icon && 'pl-3.5 ml-[calc(0.775rem)]'
                    )}
                >
                    {substeps.map((substep, substepIndex) => {
                        const isCurrentSubstep = substepIndex === substeps.length - 1
                        const isCompletedSubstep = substepIndex < substeps.length - 1 || isCompleted

                        return (
                            <div
                                key={substepIndex}
                                className="animate-fade-in"
                                style={{
                                    animationDelay: `${substepIndex * 50}ms`,
                                }}
                            >
                                <MarkdownMessage
                                    id={id}
                                    className={clsx(
                                        'leading-relaxed',
                                        isFailed && 'text-danger',
                                        !isFailed && isCompletedSubstep && 'text-muted',
                                        !isFailed && isCurrentSubstep && !isCompleted && 'text-secondary'
                                    )}
                                    content={handleThreeDots(substep ?? '', true)}
                                />
                            </div>
                        )
                    })}
                </div>
            )}
        </div>
    )
}

interface ReasoningAnswerProps {
    content: string
    completed: boolean
    id: string
    showCompletionIcon?: boolean
}

function ReasoningAnswer({ content, completed, id, showCompletionIcon = true }: ReasoningAnswerProps): JSX.Element {
    return (
        <AssistantActionComponent
            id={id}
            content={completed ? 'Thought' : content}
            substeps={completed ? [content] : []}
            state={completed ? ExecutionStatus.Completed : ExecutionStatus.InProgress}
            icon={<IconBrain className="pt-[0.03rem]" />} // The brain icon is slightly too high, so we need to offset it
            animate={true}
            showCompletionIcon={showCompletionIcon}
        />
    )
}

interface ToolCallsAnswerProps {
    toolCalls: EnhancedToolCall[]
}

function ToolCallsAnswer({ toolCalls }: ToolCallsAnswerProps): JSX.Element {
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
                        const commentary = toolCall.args.commentary as string
                        const updates = toolCall.updates ?? []
                        const definition = getToolDefinition(toolCall.name)
                        let description = `Executing ${toolCall.name}`
                        if (definition) {
                            if (definition.displayFormatter) {
                                description = definition.displayFormatter(toolCall)
                            }
                            if (commentary) {
                                description = commentary
                            }
                        }
                        return (
                            <AssistantActionComponent
                                key={toolCall.id}
                                id={toolCall.id}
                                content={description}
                                substeps={updates}
                                state={toolCall.status}
                                icon={definition?.icon || <IconWrench />}
                                showCompletionIcon={true}
                            />
                        )
                    })}
                </div>
            )}
        </>
    )
}

const visualizationTypeToQuery = (visualization: VisualizationItem): InsightVizNode | DataVisualizationNode | null => {
    const source = castAssistantQuery(visualization.answer)
    if (isHogQLQuery(source)) {
        return { kind: NodeKind.DataVisualizationNode, source: source } satisfies DataVisualizationNode
    }
    return { kind: NodeKind.InsightVizNode, source, showHeader: false } satisfies InsightVizNode
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
            {isSummaryShown && (
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

function InsightSuggestionButton({ tabId }: { tabId: string }): JSX.Element {
    const { insight } = useValues(insightSceneLogic({ tabId }))
    const insightProps = { dashboardItemId: insight?.short_id }
    const { suggestedQuery, previousQuery } = useValues(insightLogic(insightProps))
    const { onRejectSuggestedInsight, onReapplySuggestedInsight } = useActions(insightLogic(insightProps))

    return (
        <>
            {suggestedQuery && (
                <LemonButton
                    onClick={() => {
                        if (previousQuery) {
                            onRejectSuggestedInsight()
                        } else {
                            onReapplySuggestedInsight()
                        }
                    }}
                    sideIcon={previousQuery ? <IconX /> : <IconRefresh />}
                    size="xsmall"
                    tooltip={previousQuery ? 'Reject changes' : 'Reapply changes'}
                />
            )}
        </>
    )
}

const VisualizationAnswer = React.memo(function VisualizationAnswer({
    message,
    status,
    isEditingInsight,
    activeTabId,
    activeSceneId,
}: {
    message: VisualizationMessage
    status?: MessageStatus
    isEditingInsight: boolean
    activeTabId?: string | null
    activeSceneId?: string | null
}): JSX.Element | null {
    const [isSummaryShown, setIsSummaryShown] = useState(false)
    const [isCollapsed, setIsCollapsed] = useState(isEditingInsight)

    useLayoutEffect(() => {
        setIsCollapsed(isEditingInsight)
    }, [isEditingInsight])

    const query = useMemo(() => visualizationTypeToQuery(message), [message])

    return status !== 'completed'
        ? null
        : query && (
              <>
                  <MessageTemplate
                      type="ai"
                      className="w-full"
                      wrapperClassName="w-full"
                      boxClassName={clsx('flex flex-col w-full', isFunnelsQuery(message.answer) ? 'h-[580px]' : 'h-96')}
                  >
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
                              {isEditingInsight && activeTabId && activeSceneId === Scene.Insight && (
                                  <InsightSuggestionButton tabId={activeTabId} />
                              )}
                              {!isEditingInsight && (
                                  <LemonButton
                                      to={
                                          message.short_id
                                              ? urls.insightView(message.short_id as InsightShortId)
                                              : urls.insightNew({ query })
                                      }
                                      icon={<IconOpenInNew />}
                                      size="xsmall"
                                      tooltip={message.short_id ? 'Open insight' : 'Open as new insight'}
                                  />
                              )}
                              <LemonButton
                                  icon={isCollapsed ? <IconEye /> : <IconHide />}
                                  onClick={() => setIsCollapsed(!isCollapsed)}
                                  size="xsmall"
                                  className="-m-1 shrink"
                                  tooltip={isCollapsed ? 'Show visualization' : 'Hide visualization'}
                              />
                          </div>
                      </div>
                      {isSummaryShown && (
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
                  </MessageTemplate>
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
                    return { query, title: visualization.plan || `Insight #${index + 1}` }
                }
                return null
            })
            .filter(Boolean) as Array<{ query: InsightVizNode | DataVisualizationNode; title: string }>
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
    insights: Array<{ query: InsightVizNode | DataVisualizationNode; title: string }>
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

function SuccessActions({ retriable }: { retriable: boolean }): JSX.Element {
    const { traceId } = useValues(maxThreadLogic)
    const { retryLastMessage } = useActions(maxThreadLogic)
    const { user } = useValues(userLogic)

    const [rating, setRating] = useState<'good' | 'bad' | null>(null)
    const [feedback, setFeedback] = useState<string>('')
    const [feedbackInputStatus, setFeedbackInputStatus] = useState<'hidden' | 'pending' | 'submitted'>('hidden')

    function submitRating(newRating: 'good' | 'bad'): void {
        if (rating || !traceId) {
            return // Already rated
        }
        setRating(newRating)
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
                {rating !== 'bad' && (
                    <LemonButton
                        icon={rating === 'good' ? <IconThumbsUpFilled /> : <IconThumbsUp />}
                        type="tertiary"
                        size="xsmall"
                        tooltip="Good answer"
                        onClick={() => submitRating('good')}
                    />
                )}
                {rating !== 'good' && (
                    <LemonButton
                        icon={rating === 'bad' ? <IconThumbsDownFilled /> : <IconThumbsDown />}
                        type="tertiary"
                        size="xsmall"
                        tooltip="Bad answer"
                        onClick={() => submitRating('bad')}
                    />
                )}
                {retriable && (
                    <LemonButton
                        icon={<IconRefresh />}
                        type="tertiary"
                        size="xsmall"
                        tooltip="Try again"
                        onClick={() => retryLastMessage()}
                    />
                )}
                {(user?.is_staff || location.hostname === 'localhost') && traceId && (
                    <LemonButton
                        to={`${
                            location.hostname !== 'localhost'
                                ? 'https://us.posthog.com/project/2'
                                : `${window.location.origin}/project/2`
                        }${urls.llmAnalyticsTrace(traceId)}`}
                        icon={<IconEye />}
                        type="tertiary"
                        size="xsmall"
                        tooltip="View trace in LLM analytics"
                    />
                )}
            </div>
            {feedbackInputStatus !== 'hidden' && (
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
