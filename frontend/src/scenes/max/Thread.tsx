import { IconThumbsDown, IconThumbsDownFilled, IconThumbsUp, IconThumbsUpFilled, IconX } from '@posthog/icons'
import { LemonButton, LemonInput, Spinner } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useValues } from 'kea'
import { BreakdownSummary, PropertiesSummary, SeriesSummary } from 'lib/components/Cards/InsightCard/InsightDetails'
import { TopHeading } from 'lib/components/Cards/InsightCard/TopHeading'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import posthog from 'posthog-js'
import React, { useMemo, useRef, useState } from 'react'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import {
    AssistantMessageType,
    HumanMessage,
    InsightVizNode,
    NodeKind,
    TrendsQuery,
    VisualizationMessage,
} from '~/queries/schema'

import { maxLogic, MessageStatus, ThreadMessage } from './maxLogic'
import { isHumanMessage, isVisualizationMessage } from './utils'

export function Thread(): JSX.Element | null {
    const { thread, threadLoading } = useValues(maxLogic)

    return (
        <div className="flex flex-col items-stretch w-full max-w-200 self-center gap-2 grow m-4">
            {thread.map((message, index) => {
                if (isHumanMessage(message)) {
                    return (
                        <Message
                            key={index}
                            type="human"
                            className={message.status === 'error' ? 'border-danger' : undefined}
                        >
                            {message.content || <i>No text</i>}
                        </Message>
                    )
                }

                if (isVisualizationMessage(message)) {
                    return (
                        <Answer
                            key={index}
                            message={message}
                            status={message.status}
                            previousMessage={thread[index - 1]}
                        />
                    )
                }

                return null
            })}
            {threadLoading && (
                <Message type="ai" className="w-fit select-none">
                    <div className="flex items-center gap-2">
                        Let me think…
                        <Spinner className="text-xl" />
                    </div>
                </Message>
            )}
        </div>
    )
}

const Message = React.forwardRef<HTMLDivElement, React.PropsWithChildren<{ type: 'human' | 'ai'; className?: string }>>(
    function Message({ type, children, className }, ref): JSX.Element {
        if (type === AssistantMessageType.Human) {
            return (
                <div className={clsx('mt-1 mb-3 text-2xl font-medium', className)} ref={ref}>
                    {children}
                </div>
            )
        }

        return (
            <div className={clsx('border p-2 rounded bg-bg-light', className)} ref={ref}>
                {children}
            </div>
        )
    }
)

function Answer({
    message,
    status,
    previousMessage,
}: {
    message: VisualizationMessage
    status?: MessageStatus
    previousMessage: ThreadMessage
}): JSX.Element {
    const query = useMemo<InsightVizNode | null>(() => {
        if (message.answer) {
            return {
                kind: NodeKind.InsightVizNode,
                source: message.answer as TrendsQuery,
                showHeader: true,
            }
        }

        return null
    }, [message])

    return (
        <>
            {message.reasoning_steps && (
                <Message type="ai">
                    <ul className="list-disc ml-4">
                        {message.reasoning_steps.map((step, index) => (
                            <li key={index}>{step}</li>
                        ))}
                    </ul>
                </Message>
            )}
            {status === 'completed' && query && (
                <>
                    <Message type="ai">
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
                    </Message>
                    {isHumanMessage(previousMessage) && (
                        <AnswerActions message={message} previousMessage={previousMessage} />
                    )}
                </>
            )}
        </>
    )
}

function AnswerActions({
    message,
    previousMessage,
}: {
    message: VisualizationMessage
    previousMessage: HumanMessage
}): JSX.Element {
    const [rating, setRating] = useState<'good' | 'bad' | null>(null)
    const [feedback, setFeedback] = useState<string>('')
    const [feedbackInputStatus, setFeedbackInputStatus] = useState<'hidden' | 'pending' | 'submitted'>('hidden')
    const hasScrolledFeedbackInputIntoView = useRef<boolean>(false)

    function submitRating(newRating: 'good' | 'bad'): void {
        if (rating) {
            return // Already rated
        }
        setRating(newRating)
        posthog.capture('chat rating', {
            question: previousMessage.content,
            answer: JSON.stringify(message.answer),
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
            question: previousMessage.content,
            answer: JSON.stringify(message.answer),
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
            </div>
            {feedbackInputStatus !== 'hidden' && (
                <Message
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
                </Message>
            )}
        </>
    )
}
