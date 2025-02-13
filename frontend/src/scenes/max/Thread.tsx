import {
    IconRefresh,
    IconThumbsDown,
    IconThumbsDownFilled,
    IconThumbsUp,
    IconThumbsUpFilled,
    IconWarning,
    IconX,
} from '@posthog/icons'
import { LemonButton, LemonButtonPropsBase, LemonInput, ProfilePicture, Spinner, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { BreakdownSummary, PropertiesSummary, SeriesSummary } from 'lib/components/Cards/InsightCard/InsightDetails'
import { TopHeading } from 'lib/components/Cards/InsightCard/TopHeading'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import posthog from 'posthog-js'
import React, { useMemo, useState } from 'react'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'
import { twMerge } from 'tailwind-merge'

import { Query } from '~/queries/Query/Query'
import {
    AssistantForm,
    AssistantMessage,
    FailureMessage,
    VisualizationMessage,
} from '~/queries/schema/schema-assistant-messages'
import { InsightVizNode, NodeKind } from '~/queries/schema/schema-general'

import { maxLogic, MessageStatus, ThreadMessage } from './maxLogic'
import {
    castAssistantQuery,
    isAssistantMessage,
    isFailureMessage,
    isHumanMessage,
    isReasoningMessage,
    isVisualizationMessage,
} from './utils'

export function Thread(): JSX.Element | null {
    const { threadGrouped } = useValues(maxLogic)

    return (
        <div className="flex flex-col items-stretch w-full max-w-200 self-center gap-2 grow p-4">
            {threadGrouped.map((group, index) => (
                <MessageGroup key={index} messages={group} index={index} isFinal={index === threadGrouped.length - 1} />
            ))}
        </div>
    )
}

interface MessageGroupProps {
    messages: ThreadMessage[]
    isFinal: boolean
    index: number
}

function MessageGroup({ messages, isFinal: isFinalGroup }: MessageGroupProps): JSX.Element {
    const { user } = useValues(userLogic)

    const groupType = messages[0].type === 'human' ? 'human' : 'ai'

    return (
        <div className={clsx('relative flex gap-2', groupType === 'human' ? 'flex-row-reverse ml-10' : 'mr-10')}>
            <Tooltip placement={groupType === 'human' ? 'right' : 'left'} title={groupType === 'human' ? 'You' : 'Max'}>
                <ProfilePicture
                    user={
                        groupType === 'human'
                            ? { ...user, hedgehog_config: undefined }
                            : { hedgehog_config: { ...user?.hedgehog_config, use_as_profile: true } }
                    }
                    size="lg"
                    className="mt-1 border"
                />
            </Tooltip>
            <div
                className={clsx(
                    'flex flex-col gap-2 min-w-0 w-full',
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
                                <LemonMarkdown>{message.content || '*No text.*'}</LemonMarkdown>
                            </MessageTemplate>
                        )
                    } else if (isAssistantMessage(message) || isFailureMessage(message)) {
                        return (
                            <TextAnswer
                                key={key}
                                message={message}
                                interactable={messageIndex === messages.length - 1}
                                isFinalGroup={isFinalGroup}
                            />
                        )
                    } else if (isVisualizationMessage(message)) {
                        return <VisualizationAnswer key={messageIndex} message={message} status={message.status} />
                    } else if (isReasoningMessage(message)) {
                        return (
                            <MessageTemplate key={key} type="ai">
                                <div className="flex items-center gap-2">
                                    <span>{message.content}…</span>
                                    <Spinner className="text-xl" />
                                </div>
                                {message.substeps?.map((substep, substepIndex) => (
                                    <LemonMarkdown
                                        key={substepIndex}
                                        className="mt-1.5 leading-6 px-1 text-[0.6875rem] font-semibold bg-surface-primary rounded w-fit"
                                    >
                                        {substep}
                                    </LemonMarkdown>
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
        </div>
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
            className={twMerge('flex flex-col gap-1 w-full', type === 'human' ? 'items-end' : 'items-start', className)}
            ref={ref}
        >
            <div
                className={twMerge(
                    'border py-2 px-3 rounded-lg bg-surface-primary',
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
    message: (AssistantMessage | FailureMessage) & ThreadMessage
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
            <LemonMarkdown>
                {message.content || '*Max has failed to generate an answer. Please try again.*'}
            </LemonMarkdown>
        </MessageTemplate>
    )
})

interface AssistantMessageFormProps {
    form: AssistantForm
}

function AssistantMessageForm({ form }: AssistantMessageFormProps): JSX.Element {
    const { askMax } = useActions(maxLogic)
    return (
        <div className="flex flex-wrap gap-2 mt-1">
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

function VisualizationAnswer({
    message,
    status,
}: {
    message: VisualizationMessage
    status?: MessageStatus
}): JSX.Element | null {
    const query = useMemo<InsightVizNode | null>(() => {
        if (message.answer) {
            return {
                kind: NodeKind.InsightVizNode,
                source: castAssistantQuery(message.answer),
                showHeader: true,
            }
        }

        return null
    }, [message])

    return status !== 'completed'
        ? null
        : query && (
              <>
                  <MessageTemplate type="ai" className="w-full" boxClassName="w-full">
                      <div className="min-h-80 flex">
                          <Query query={query} readOnly embedded />
                      </div>
                      <div className="relative mb-1">
                          <LemonButton
                              to={urls.insightNew({ query })}
                              sideIcon={<IconOpenInNew />}
                              size="xsmall"
                              targetBlank
                              className="absolute right-0 -top-px"
                          >
                              Open as new insight
                          </LemonButton>
                          <SeriesSummary query={query.source} heading={<TopHeading query={query} />} />
                          <div className="flex flex-wrap gap-4 mt-1 *:grow">
                              <PropertiesSummary properties={query.source.properties} />
                              <BreakdownSummary query={query.source} />
                          </div>
                      </div>
                  </MessageTemplate>
              </>
          )
}

function RetriableFailureActions(): JSX.Element {
    const { retryLastMessage } = useActions(maxLogic)

    return (
        <LemonButton
            icon={<IconRefresh />}
            type="tertiary"
            size="small"
            tooltip="Try again"
            onClick={() => retryLastMessage()}
        >
            Try again
        </LemonButton>
    )
}

function SuccessActions({ retriable }: { retriable: boolean }): JSX.Element {
    const { traceId } = useValues(maxLogic)
    const { retryLastMessage } = useActions(maxLogic)

    const [rating, setRating] = useState<'good' | 'bad' | null>(null)
    const [feedback, setFeedback] = useState<string>('')
    const [feedbackInputStatus, setFeedbackInputStatus] = useState<'hidden' | 'pending' | 'submitted'>('hidden')

    function submitRating(newRating: 'good' | 'bad'): void {
        if (rating) {
            return // Already rated
        }
        setRating(newRating)
        posthog.capture('$ai_metric', {
            $ai_metric_name: 'quality',
            $ai_metric_value: newRating,
            $ai_trace_id: traceId,
        })
        if (newRating === 'bad') {
            setFeedbackInputStatus('pending')
        }
    }

    function submitFeedback(): void {
        if (!feedback) {
            return // Input is empty
        }
        posthog.capture('$ai_feedback', {
            $ai_feedback_text: feedback,
            $ai_trace_id: traceId,
        })
        setFeedbackInputStatus('submitted')
    }

    return (
        <>
            <div className="flex items-center">
                {rating !== 'bad' && (
                    <LemonButton
                        icon={rating === 'good' ? <IconThumbsUpFilled /> : <IconThumbsUp />}
                        type="tertiary"
                        size="small"
                        tooltip="Good answer"
                        onClick={() => submitRating('good')}
                    />
                )}
                {rating !== 'good' && (
                    <LemonButton
                        icon={rating === 'bad' ? <IconThumbsDownFilled /> : <IconThumbsDown />}
                        type="tertiary"
                        size="small"
                        tooltip="Bad answer"
                        onClick={() => submitRating('bad')}
                    />
                )}
                {retriable && (
                    <LemonButton
                        icon={<IconRefresh />}
                        type="tertiary"
                        size="small"
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
                            onClick={() => setFeedbackInputStatus('hidden')}
                        />
                    </div>
                    {feedbackInputStatus === 'pending' && (
                        <div className="flex w-full gap-2 items-center mt-1.5">
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
