import {
    IconCollapse,
    IconExpand,
    IconEye,
    IconHide,
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
    LemonInput,
    LemonSkeleton,
    ProfilePicture,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { BreakdownSummary, PropertiesSummary, SeriesSummary } from 'lib/components/Cards/InsightCard/InsightDetails'
import { TopHeading } from 'lib/components/Cards/InsightCard/TopHeading'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import posthog from 'posthog-js'
import React, { useEffect, useMemo, useState } from 'react'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'
import { twMerge } from 'tailwind-merge'

import { Query } from '~/queries/Query/Query'
import {
    AssistantForm,
    AssistantMessage,
    AssistantToolCallMessage,
    FailureMessage,
    VisualizationMessage,
} from '~/queries/schema/schema-assistant-messages'
import { DataVisualizationNode, InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { isHogQLQuery } from '~/queries/utils'
import { ProductKey } from '~/types'

import { ContextSummary } from './Context'
import { MarkdownMessage } from './MarkdownMessage'
import { maxGlobalLogic } from './maxGlobalLogic'
import { maxLogic, MessageStatus, ThreadMessage } from './maxLogic'
import { maxThreadLogic } from './maxThreadLogic'
import {
    castAssistantQuery,
    isAssistantMessage,
    isAssistantToolCallMessage,
    isFailureMessage,
    isHumanMessage,
    isReasoningMessage,
    isVisualizationMessage,
} from './utils'
import { supportLogic } from 'lib/components/Support/supportLogic'

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
                        <ProductIntroduction
                            isEmpty
                            productName="Max"
                            productKey={ProductKey.MAX}
                            thingName="message"
                            titleOverride="Start chatting with Max"
                            description="Max is an AI product analyst in PostHog that answers data questions, gets things done in UI, and provides insights from PostHog's documentation."
                            docsURL="https://posthog.com/docs/data/max-ai"
                        />
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
    const { tools } = useValues(maxGlobalLogic)

    const groupType = messages[0].type === 'human' ? 'human' : 'ai'
    const isEditingInsight = tools?.some((tool) => tool.name === 'create_and_query_insight')

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
                                <MarkdownMessage
                                    content={message.content || '*No text.*'}
                                    id={message.id || 'no-text'}
                                />
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
                                isEditingInsight={isEditingInsight}
                            />
                        )
                    } else if (isReasoningMessage(message)) {
                        return (
                            <MessageTemplate key={key} type="ai">
                                <div className="flex items-center gap-1.5">
                                    <Spinner className="text-xl" />
                                    <span>{message.content}…</span>
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
        if (message.status !== 'completed') {
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

const VisualizationAnswer = React.memo(function VisualizationAnswer({
    message,
    status,
    isEditingInsight,
}: {
    message: VisualizationMessage
    status?: MessageStatus
    isEditingInsight: boolean
}): JSX.Element | null {
    const { insight } = useValues(insightSceneLogic)

    const [isSummaryShown, setIsSummaryShown] = useState(false)
    const [isCollapsed, setIsCollapsed] = useState(isEditingInsight)
    // const [isApplied, setIsApplied] = useState(false)

    // Get insight props for the logic
    const insightProps = { dashboardItemId: insight?.short_id }
    const { previousQuery } = useValues(insightLogic(insightProps))
    const { onRejectSuggestedInsight } = useActions(insightLogic(insightProps))

    useEffect(() => {
        setIsCollapsed(isEditingInsight)
    }, [isEditingInsight])

    const query = useMemo<InsightVizNode | DataVisualizationNode | null>(() => {
        if (message.answer) {
            const source = castAssistantQuery(message.answer)
            if (isHogQLQuery(source)) {
                return { kind: NodeKind.DataVisualizationNode, source: source } satisfies DataVisualizationNode
            }
            return { kind: NodeKind.InsightVizNode, source, showHeader: true } satisfies InsightVizNode
        }

        return null
    }, [message])

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
                              {isEditingInsight && previousQuery && (
                                  <LemonButton
                                      onClick={() => onRejectSuggestedInsight()}
                                      // status="danger"
                                      icon={<IconX />}
                                      size="xsmall"
                                      tooltip="Reject Max's changes"
                                  />
                              )}
                              {isEditingInsight && (
                                  <LemonButton
                                      to={urls.insightNew({ query })}
                                      icon={<IconOpenInNew />}
                                      size="xsmall"
                                      targetBlank
                                      tooltip="Open as new insight"
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
                                      <BreakdownSummary query={query.source} />
                                  </div>
                              )}
                          </>
                      )}
                  </MessageTemplate>
              </>
          )
})

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
                `Trace: https://us.posthog.com/project/2/llm-observability/traces/${traceId}`,
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
