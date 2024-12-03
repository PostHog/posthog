import {
    IconRefresh,
    IconThumbsDown,
    IconThumbsDownFilled,
    IconThumbsUp,
    IconThumbsUpFilled,
    IconWarning,
    IconX,
} from '@posthog/icons'
import { LemonButton, LemonInput, ProfilePicture, Spinner, Tooltip } from '@posthog/lemon-ui'
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
    AssistantMessage,
    FailureMessage,
    HumanMessage,
    InsightVizNode,
    NodeKind,
    VisualizationMessage,
} from '~/queries/schema'

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

function MessageGroup({ messages, isFinal: isGroupFinal, index: messageGroupIndex }: MessageGroupProps): JSX.Element {
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
                    if (isHumanMessage(message)) {
                        return (
                            <MessageTemplate
                                key={messageIndex}
                                type="human"
                                boxClassName={message.status === 'error' ? 'border-danger' : undefined}
                            >
                                <LemonMarkdown>{message.content || '*No text.*'}</LemonMarkdown>
                            </MessageTemplate>
                        )
                    } else if (isAssistantMessage(message) || isFailureMessage(message)) {
                        return (
                            <TextAnswer
                                key={messageIndex}
                                message={message}
                                rateable={messageIndex === messages.length - 1}
                                retriable={messageIndex === messages.length - 1 && isGroupFinal}
                                messageGroupIndex={messageGroupIndex}
                            />
                        )
                    } else if (isVisualizationMessage(message)) {
                        return <VisualizationAnswer key={messageIndex} message={message} status={message.status} />
                    } else if (isReasoningMessage(message)) {
                        return (
                            <MessageTemplate key={messageIndex} type="ai">
                                <div className="flex items-center gap-2">
                                    <span>{message.content}…</span>
                                    <Spinner className="text-xl" />
                                </div>
                                {message.substeps?.map((substep, substepIndex) => (
                                    <LemonMarkdown
                                        key={substepIndex}
                                        className="mt-1.5 leading-6 px-1 text-[0.6875rem] font-semibold bg-accent-3000 rounded w-fit"
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
                    'border py-2 px-3 rounded-lg bg-bg-light',
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
    rateable: boolean
    retriable: boolean
    messageGroupIndex: number
}

const TextAnswer = React.forwardRef<HTMLDivElement, TextAnswerProps>(function TextAnswer(
    { message, rateable, retriable, messageGroupIndex },
    ref
) {
    return (
        <MessageTemplate
            type="ai"
            boxClassName={message.status === 'error' || message.type === 'ai/failure' ? 'border-danger' : undefined}
            ref={ref}
            action={
                message.status === 'completed' &&
                message.type === 'ai/failure' &&
                !message.content?.includes('usage limit') && // Don't show retry button when rate-limited
                retriable ? (
                    <RetriableFailureActions />
                ) : message.status === 'completed' && message.type === 'ai' && rateable ? (
                    // Show answer actions if the assistant's response is complete at this point
                    <SuccessActions retriable={retriable} messageGroupIndex={messageGroupIndex} />
                ) : null
            }
        >
            <LemonMarkdown>
                {message.content || '*Max has failed to generate an answer. Please try again.*'}
            </LemonMarkdown>
        </MessageTemplate>
    )
})

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
                              to={urls.insightNew(undefined, undefined, query)}
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

function SuccessActions({
    messageGroupIndex,
    retriable,
}: {
    messageGroupIndex: number
    retriable: boolean
}): JSX.Element {
    const { threadGrouped } = useValues(maxLogic)
    const { retryLastMessage } = useActions(maxLogic)

    const [rating, setRating] = useState<'good' | 'bad' | null>(null)
    const [feedback, setFeedback] = useState<string>('')
    const [feedbackInputStatus, setFeedbackInputStatus] = useState<'hidden' | 'pending' | 'submitted'>('hidden')

    const [relevantHumanMessage, relevantVisualizationMessage] = useMemo(() => {
        // We need to find the relevant visualization message (which might be a message earlier if the most recent one
        // is a results summary message), and the human message that triggered it.
        const visualizationMessage = threadGrouped[messageGroupIndex].find(
            isVisualizationMessage
        ) as VisualizationMessage
        const humanMessage = threadGrouped[messageGroupIndex - 1][0] as HumanMessage
        return [humanMessage, visualizationMessage]
    }, [threadGrouped, messageGroupIndex])

    function submitRating(newRating: 'good' | 'bad'): void {
        if (rating) {
            return // Already rated
        }
        setRating(newRating)
        posthog.capture('chat rating', {
            question: relevantHumanMessage.content,
            answer: JSON.stringify(relevantVisualizationMessage.answer),
            answer_rating: rating,
        })
        if (newRating === 'bad') {
            setFeedbackInputStatus('pending')
        }
    }

    function submitFeedback(): void {
        if (!feedback) {
            return // Input is empty
        }
        posthog.capture('chat feedback', {
            question: relevantHumanMessage.content,
            answer: JSON.stringify(relevantVisualizationMessage.answer),
            feedback,
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
                    <div className="flex items-center">
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
