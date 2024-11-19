import {
    IconRefresh,
    IconThumbsDown,
    IconThumbsDownFilled,
    IconThumbsUp,
    IconThumbsUpFilled,
    IconX,
} from '@posthog/icons'
import { LemonButton, LemonInput, Spinner } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { BreakdownSummary, PropertiesSummary, SeriesSummary } from 'lib/components/Cards/InsightCard/InsightDetails'
import { TopHeading } from 'lib/components/Cards/InsightCard/TopHeading'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import posthog from 'posthog-js'
import React, { useMemo, useRef, useState } from 'react'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import {
    AssistantMessage,
    AssistantMessageType,
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
    const { thread, threadLoading } = useValues(maxLogic)

    return (
        <div className="flex flex-col items-stretch w-full max-w-200 self-center gap-2 grow p-4">
            {thread.map((message, index) => {
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
                    return <div key={index}>{message.content}</div>
                }
                return null // We currently skip other types of messages
            })}
            {threadLoading && (
                <MessageTemplate type="ai" className="w-fit select-none">
                    <div className="flex items-center gap-2">
                        Let me think…
                        <Spinner className="text-xl" />
                    </div>
                </MessageTemplate>
            )}
        </div>
    )
}

const MessageTemplate = React.forwardRef<
    HTMLDivElement,
    { type: 'human' | 'ai'; className?: string; action?: React.ReactNode; children: React.ReactNode }
>(function MessageTemplate({ type, children, className, action }, ref) {
    if (type === AssistantMessageType.Human) {
        return (
            <div className={clsx('mt-1 mb-3 text-2xl font-medium', className)} ref={ref}>
                {children}
            </div>
        )
    }

    return (
        <div className="space-y-2">
            <div className={clsx('border p-2 rounded bg-bg-light', className)} ref={ref}>
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
                      <div className="h-96 flex">
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
            type="secondary"
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
    const hasScrolledFeedbackInputIntoView = useRef<boolean>(false)

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
                <MessageTemplate
                    type="ai"
                    ref={(el) => {
                        if (el && !hasScrolledFeedbackInputIntoView.current) {
                            // When the feedback input is first rendered, scroll it into view
                            el.scrollIntoView({ behavior: 'smooth' })
                            hasScrolledFeedbackInputIntoView.current = true
                        }
                    }}
                >
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
