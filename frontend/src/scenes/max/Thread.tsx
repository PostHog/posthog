import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import React, { useEffect, useMemo, useState } from 'react'
import { twMerge } from 'tailwind-merge'

import {
    IconCheck,
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
    IconX,
} from '@posthog/icons'
import {
    LemonButton,
    LemonButtonPropsBase,
    LemonCheckbox,
    LemonDialog,
    LemonInput,
    LemonSkeleton,
    ProfilePicture,
    Tooltip,
} from '@posthog/lemon-ui'

import {
    InsightBreakdownSummary,
    PropertiesSummary,
    SeriesSummary,
} from 'lib/components/Cards/InsightCard/InsightDetails'
import { TopHeading } from 'lib/components/Cards/InsightCard/TopHeading'
import { NotFound } from 'lib/components/NotFound'
import { supportLogic } from 'lib/components/Support/supportLogic'
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
    AssistantToolCallMessage,
    FailureMessage,
    MultiVisualizationMessage,
    NotebookUpdateMessage,
    PlanningMessage,
    PlanningStepStatus,
    TaskExecutionMessage,
    TaskExecutionStatus,
    VisualizationItem,
    VisualizationMessage,
} from '~/queries/schema/schema-assistant-messages'
import { DataVisualizationNode, InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { isHogQLQuery } from '~/queries/utils'
import { InsightShortId } from '~/types'

import { ContextSummary } from './Context'
import { MarkdownMessage } from './MarkdownMessage'
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
    isPlanningMessage,
    isReasoningMessage,
    isTaskExecutionMessage,
    isVisualizationMessage,
} from './utils'

export function Thread({ className }: { className?: string }): JSX.Element | null {
    const { conversationLoading, conversationId } = useValues(maxLogic)
    const { threadGrouped } = useValues(maxThreadLogic)

    return (
        <div
            className={twMerge(
                '@container/thread flex flex-col items-stretch w-full max-w-200 self-center gap-1.5 grow',
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
                threadGrouped.map((group: ThreadMessage[], index: number) => (
                    <MessageGroup
                        // Reset the components when the thread changes
                        key={`${conversationId}-${index}`}
                        messages={group}
                        isFinal={index === threadGrouped.length - 1}
                    />
                ))
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

function MessageGroupContainer({
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
                'relative flex gap-1.5',
                groupType === 'human' ? 'flex-row-reverse ml-4 @md/thread:ml-10 ' : 'mr-4 @md/thread:mr-10',
                className
            )}
        >
            {children}
        </div>
    )
}

interface MessageGroupProps {
    messages: ThreadMessage[]
    isFinal: boolean
}

function MessageGroup({ messages, isFinal: isFinalGroup }: MessageGroupProps): JSX.Element {
    const { user } = useValues(userLogic)
    const { editInsightToolRegistered } = useValues(maxGlobalLogic)

    const groupType = messages[0].type === 'human' ? 'human' : 'ai'

    return (
        <MessageGroupContainer groupType={groupType}>
            <Tooltip title={groupType === 'human' ? 'You' : 'Max'}>
                <ProfilePicture
                    user={
                        groupType === 'human'
                            ? { ...user, hedgehog_config: undefined }
                            : { hedgehog_config: { ...user?.hedgehog_config, use_as_profile: true } }
                    }
                    size="lg"
                    className="hidden @md/thread:flex mt-1 border"
                />
            </Tooltip>
            <div
                className={clsx(
                    'flex flex-col gap-1.5 min-w-0 w-full',
                    groupType === 'human' ? 'items-end' : 'items-start'
                )}
            >
                {messages.map((message, messageIndex) => {
                    const key = message.id || messageIndex
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
                                                    This is a Max command:
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
                    } else if (
                        isAssistantMessage(message) ||
                        isAssistantToolCallMessage(message) ||
                        isFailureMessage(message)
                    ) {
                        return (
                            <TextAnswer
                                key={key}
                                message={message}
                                interactable={messageIndex === messages.length - 1}
                                isFinalGroup={isFinalGroup}
                            />
                        )
                    } else if (isVisualizationMessage(message)) {
                        return (
                            <VisualizationAnswer
                                key={messageIndex}
                                message={message}
                                status={message.status}
                                isEditingInsight={editInsightToolRegistered}
                            />
                        )
                    } else if (isMultiVisualizationMessage(message)) {
                        return <MultiVisualizationAnswer key={key} message={message} />
                    } else if (isReasoningMessage(message)) {
                        return (
                            <MessageTemplate key={key} type="ai">
                                <div className="flex items-center gap-2">
                                    <img
                                        src="https://res.cloudinary.com/dmukukwp6/image/upload/loading_bdba47912e.gif"
                                        className="size-7 -m-1" // At the "native" size-6 (24px), the icons are a tad too small
                                    />
                                    <span className="font-medium">{message.content}…</span>
                                </div>
                                {message.substeps?.map((substep, substepIndex) => (
                                    <MarkdownMessage
                                        key={substepIndex}
                                        id={message.id || messageIndex.toString()}
                                        className="mt-1.5 leading-6 px-1 text-[0.6875rem] font-semibold bg-surface-secondary rounded w-fit"
                                        content={substep}
                                    />
                                ))}
                            </MessageTemplate>
                        )
                    } else if (isNotebookUpdateMessage(message)) {
                        return <NotebookUpdateAnswer key={key} message={message} />
                    } else if (isPlanningMessage(message)) {
                        return <PlanningAnswer key={key} message={message} />
                    } else if (isTaskExecutionMessage(message)) {
                        return <TaskExecutionAnswer key={key} message={message} />
                    }
                    return null // We currently skip other types of messages
                })}
                {messages.at(-1)?.status === 'error' && (
                    <MessageTemplate type="ai" boxClassName="border-warning">
                        <div className="flex items-center gap-1.5">
                            <IconWarning className="text-xl text-warning" />
                            <i>Max is generating this answer one more time because the previous attempt has failed.</i>
                        </div>
                    </MessageTemplate>
                )}
            </div>
        </MessageGroupContainer>
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
        <MessageGroupContainer className={clsx('items-center', className)} groupType={groupType}>
            <LemonSkeleton className="w-8 h-8 rounded-full hidden border @md/thread:flex" />
            <LemonSkeleton className="h-10 w-3/5 rounded-lg border" />
        </MessageGroupContainer>
    )
}

interface MessageTemplateProps {
    type: 'human' | 'ai'
    action?: React.ReactNode
    className?: string
    boxClassName?: string
    children: React.ReactNode
}

const MessageTemplate = React.forwardRef<HTMLDivElement, MessageTemplateProps>(function MessageTemplate(
    { type, children, className, boxClassName, action },
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
            <div
                className={twMerge(
                    'max-w-full border py-2 px-3 rounded-lg bg-surface-primary',
                    type === 'human' && 'font-medium',
                    boxClassName
                )}
            >
                {children}
            </div>
            {action}
        </div>
    )
})

interface TextAnswerProps {
    message: (AssistantMessage | FailureMessage | AssistantToolCallMessage) & ThreadMessage
    interactable?: boolean
    isFinalGroup?: boolean
}

const TextAnswer = React.forwardRef<HTMLDivElement, TextAnswerProps>(function TextAnswer(
    { message, interactable, isFinalGroup },
    ref
) {
    const retriable = !!(interactable && isFinalGroup)

    const action = (() => {
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

    return (
        <MessageTemplate
            type="ai"
            boxClassName={message.status === 'error' || message.type === 'ai/failure' ? 'border-danger' : undefined}
            ref={ref}
            action={action}
        >
            <MarkdownMessage
                content={message.content || '*Max has failed to generate an answer. Please try again.*'}
                id={message.id || 'error'}
            />
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
    message: PlanningMessage
}

function PlanningAnswer({ message }: PlanningAnswerProps): JSX.Element {
    return (
        <MessageTemplate type="ai">
            <div className="space-y-2">
                <h4 className="m-0 text-xs font-semibold">TO-DOs</h4>
                <div className="space-y-1.5 mt-1">
                    {message.steps.map((step, index) => (
                        <LemonCheckbox
                            key={index}
                            size="xsmall"
                            defaultChecked={step.status === PlanningStepStatus.Completed}
                            disabled={true}
                            label={
                                step.description +
                                (step.status === PlanningStepStatus.InProgress ? ' (in progress)' : '')
                            }
                            labelClassName={clsx(
                                'cursor-default! text-xs',
                                step.status === PlanningStepStatus.Completed && 'text-muted line-through',
                                step.status === PlanningStepStatus.InProgress && 'font-semibold'
                            )}
                        />
                    ))}
                </div>
            </div>
        </MessageTemplate>
    )
}

interface TaskExecutionAnswerProps {
    message: TaskExecutionMessage
}

function TaskExecutionAnswer({ message }: TaskExecutionAnswerProps): JSX.Element {
    const completedCount = message.tasks.filter((t) => t.status === TaskExecutionStatus.Completed).length
    const totalCount = message.tasks.length

    return (
        <MessageTemplate type="ai">
            <div className="flex flex-col gap-2 pb-2">
                <div className="flex items-center justify-between">
                    <h4 className="m-0 text-xs font-semibold">Tasks</h4>
                    <span className="text-xs text-muted">
                        {completedCount}/{totalCount}
                    </span>
                </div>

                <div className="flex flex-col gap-2">
                    {message.tasks.map((task, index) => (
                        <div
                            key={index}
                            className={clsx(
                                'flex items-center gap-2 rounded transition-all duration-300 py-1',
                                task.status === TaskExecutionStatus.InProgress && 'bg-accent-highlight-primary/20',
                                task.status === TaskExecutionStatus.Completed && 'opacity-60'
                            )}
                        >
                            <div className="flex-shrink-0 flex items-center justify-center size-7">
                                {task.status === TaskExecutionStatus.Completed && (
                                    <IconCheck className="text-success size-3.5" />
                                )}
                                {task.status === TaskExecutionStatus.InProgress && (
                                    <div className="size-3 rounded-full bg-border animate-pulse" />
                                )}
                                {task.status === TaskExecutionStatus.Pending && (
                                    <div className="size-3 rounded-full bg-border" />
                                )}
                                {task.status === TaskExecutionStatus.Failed && (
                                    <IconX className="text-danger size-3.5" />
                                )}
                            </div>

                            <div className="flex-1 min-w-0">
                                <div
                                    className={clsx(
                                        'text-xs transition-all duration-300',
                                        task.status === TaskExecutionStatus.Pending && 'text-muted',
                                        task.status === TaskExecutionStatus.InProgress &&
                                            'font-semibold text-primary animate-pulse',
                                        task.status === TaskExecutionStatus.Completed && 'text-muted-alt line-through',
                                        task.status === TaskExecutionStatus.Failed && 'text-danger'
                                    )}
                                >
                                    {task.description}
                                </div>

                                {task.prompt && (
                                    <div
                                        className={clsx(
                                            'text-xs mt-0.5 transition-all duration-300',
                                            task.status === TaskExecutionStatus.InProgress
                                                ? 'text-muted-alt animate-pulse'
                                                : 'text-muted',
                                            task.status === TaskExecutionStatus.Completed && 'line-through opacity-50'
                                        )}
                                    >
                                        {task.prompt}
                                    </div>
                                )}

                                {task.progress_text && task.status !== TaskExecutionStatus.Pending && (
                                    <div
                                        className={`text-xs mt-0.5 font-medium ${
                                            task.status === TaskExecutionStatus.InProgress
                                                ? 'text-primary-alt animate-pulse'
                                                : task.status === TaskExecutionStatus.Completed
                                                  ? 'text-success'
                                                  : 'text-danger'
                                        }`}
                                    >
                                        <MarkdownMessage
                                            id={index.toString()}
                                            className="mt-1.5 leading-6 px-1 text-[0.6875rem] font-semibold bg-surface-secondary rounded w-fit"
                                            content={task.progress_text}
                                        />
                                    </div>
                                )}
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        </MessageTemplate>
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
                    tooltip={previousQuery ? "Reject Max's changes" : "Reapply Max's changes"}
                />
            )}
        </>
    )
}

const VisualizationAnswer = React.memo(function VisualizationAnswer({
    message,
    status,
    isEditingInsight,
}: {
    message: VisualizationMessage
    status?: MessageStatus
    isEditingInsight: boolean
}): JSX.Element | null {
    const [isSummaryShown, setIsSummaryShown] = useState(false)
    const [isCollapsed, setIsCollapsed] = useState(isEditingInsight)
    const { activeTabId, activeSceneId } = useValues(sceneLogic)

    useEffect(() => {
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
                      boxClassName={clsx('flex flex-col w-full', !isCollapsed && 'min-h-60')}
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
    const { submitZendeskTicket } = useActions(supportLogic)
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
        if (!feedback || !traceId || !user) {
            return // Input is empty
        }
        posthog.captureTraceFeedback(traceId, feedback)
        setFeedbackInputStatus('submitted')
        // Also create a support ticket for thumbs down feedback, for the support hero to see
        submitZendeskTicket({
            name: user.first_name,
            email: user.email,
            kind: 'feedback',
            target_area: 'max-ai',
            severity_level: 'medium',
            message: [
                feedback,
                '\nℹ️ This ticket was created automatically when a user gave thumbs down feedback to Max AI.',
                `Trace: https://us.posthog.com/project/2/llm-analytics/traces/${traceId}`,
            ].join('\n'),
        })
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
                        targetBlank
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
                                placeholder="Help us improve Max…"
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
