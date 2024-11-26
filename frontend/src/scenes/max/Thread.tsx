import {
    IconRefresh,
    IconThumbsDown,
    IconThumbsDownFilled,
    IconThumbsUp,
    IconThumbsUpFilled,
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
                <MessageGroup key={index} messages={group} />
            ))}
        </div>
    )
}

function MessageGroup({ messages }: { messages: ThreadMessage[] }): JSX.Element {
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
            <div className={clsx('flex flex-col gap-2', groupType === 'human' ? 'min-w-0' : 'w-full')}>
                {messages.map((message, index) => {
                    if (isHumanMessage(message)) {
                        return (
                            <MessageTemplate
                                key={index}
                                type="human"
                                className={message.status === 'error' ? 'border-danger' : undefined}
                            >
                                <LemonMarkdown>{message.content || '*No text.*'}</LemonMarkdown>
                            </MessageTemplate>
                        )
                    } else if (isAssistantMessage(message) || isFailureMessage(message)) {
                        return <TextAnswer key={index} message={message} index={index} />
                    } else if (isVisualizationMessage(message)) {
                        return <VisualizationAnswer key={index} message={message} status={message.status} />
                    } else if (isReasoningMessage(message)) {
                        return (
                            <MessageTemplate key={index} type="ai" className="w-fit">
                                <div className="flex items-center gap-2">
                                    <span>{message.content}…</span>
                                    <Spinner className="text-xl" />
                                </div>
                            </MessageTemplate>
                        )
                    }
                    return null // We currently skip other types of messages
                })}
            </div>
        </div>
    )
}

const MessageTemplate = React.forwardRef<
    HTMLDivElement,
    { type: 'human' | 'ai'; className?: string; action?: React.ReactNode; children: React.ReactNode }
>(function MessageTemplate({ type, children, className, action }, ref) {
    return (
        <div className={clsx('flex flex-col gap-1', type === 'human' ? 'items-end' : undefined)} ref={ref}>
            <div
                className={clsx(
                    'border py-2 px-3 rounded-[20px] bg-bg-light',
                    type === 'human' && 'font-medium',
                    className
                )}
            >
                {children}
            </div>
            {action}
        </div>
    )
})

const TextAnswer = React.forwardRef<
    HTMLDivElement,
    { message: (AssistantMessage | FailureMessage) & ThreadMessage; index: number }
>(function TextAnswer({ message, index }, ref) {
    const { thread } = useValues(maxLogic)

    return (
        <MessageTemplate
            type="ai"
            className={message.status === 'error' || message.type === 'ai/failure' ? 'border-danger' : undefined}
            ref={ref}
            action={
                message.type === 'ai/failure' && index === thread.length - 1 ? (
                    <RetriableAnswerActions />
                ) : message.type === 'ai' &&
                  message.status === 'completed' &&
                  (thread[index + 1] === undefined || thread[index + 1].type === 'human') ? (
                    // Show answer actions if the assistant's response is complete at this point
                    <SuccessfulAnswerActions messageIndex={index} />
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
                  <MessageTemplate type="ai">
                      <div className="min-h-96 flex">
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

function RetriableAnswerActions(): JSX.Element {
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

function SuccessfulAnswerActions({ messageIndex }: { messageIndex: number }): JSX.Element {
    const { thread } = useValues(maxLogic)
    const { retryLastMessage } = useActions(maxLogic)

    const [rating, setRating] = useState<'good' | 'bad' | null>(null)
    const [feedback, setFeedback] = useState<string>('')
    const [feedbackInputStatus, setFeedbackInputStatus] = useState<'hidden' | 'pending' | 'submitted'>('hidden')

    const [relevantHumanMessage, relevantVisualizationMessage] = useMemo(() => {
        // We need to find the relevant visualization message (which might be a message earlier if the most recent one
        // is a results summary message), and the human message that triggered it.
        const relevantMessages = thread.slice(0, messageIndex + 1).reverse()
        const visualizationMessage = relevantMessages.find(isVisualizationMessage) as VisualizationMessage
        const humanMessage = relevantMessages.find(isHumanMessage) as HumanMessage
        return [humanMessage, visualizationMessage]
    }, [thread, messageIndex])

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
                {messageIndex === thread.length - 1 && (
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
