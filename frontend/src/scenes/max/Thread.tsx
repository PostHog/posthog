import { IconThumbsDown, IconThumbsDownFilled, IconThumbsUp, IconThumbsUpFilled, IconX } from '@posthog/icons'
import { LemonButton, LemonInput, Spinner } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useValues } from 'kea'
import { BreakdownSummary, PropertiesSummary, SeriesSummary } from 'lib/components/Cards/InsightCard/InsightDetails'
import { TopHeading } from 'lib/components/Cards/InsightCard/TopHeading'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import posthog from 'posthog-js'
import React, { useRef, useState } from 'react'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { InsightQueryNode, InsightVizNode, NodeKind } from '~/queries/schema'

import { maxLogic, ThreadMessage, TrendGenerationResult } from './maxLogic'

export function Thread(): JSX.Element | null {
    const { thread, threadLoading } = useValues(maxLogic)

    return (
        <div className="flex flex-col items-stretch w-full max-w-200 self-center gap-2 grow m-4">
            {thread.map((message, index) => {
                if (message.role === 'user' || typeof message.content === 'string') {
                    return (
                        <Message
                            key={index}
                            role={message.role}
                            className={message.status === 'error' ? 'border-danger' : undefined}
                        >
                            {message.content || <i>No text</i>}
                        </Message>
                    )
                }

                return (
                    <Answer
                        key={index}
                        message={message as ThreadMessage & { content: TrendGenerationResult }}
                        previousMessage={thread[index - 1]}
                    />
                )
            })}
            {threadLoading && (
                <Message role="assistant" className="w-fit select-none">
                    <div className="flex items-center gap-2">
                        Let me think…
                        <Spinner className="text-xl" />
                    </div>
                </Message>
            )}
        </div>
    )
}

const Message = React.forwardRef<
    HTMLDivElement,
    React.PropsWithChildren<{ role: 'user' | 'assistant'; className?: string }>
>(function Message({ role, children, className }, ref): JSX.Element {
    if (role === 'user') {
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
})

function Answer({
    message,
    previousMessage,
}: {
    message: ThreadMessage & { content: TrendGenerationResult }
    previousMessage: ThreadMessage
}): JSX.Element {
    const query: InsightVizNode = {
        kind: NodeKind.InsightVizNode,
        source: message.content?.answer as InsightQueryNode,
        showHeader: true,
    }

    return (
        <>
            {message.content?.reasoning_steps && (
                <Message role={message.role}>
                    <ul className="list-disc ml-4">
                        {message.content.reasoning_steps.map((step, index) => (
                            <li key={index}>{step}</li>
                        ))}
                    </ul>
                </Message>
            )}
            {message.status === 'completed' && message.content?.answer && (
                <>
                    <Message role={message.role}>
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
                    <AnswerActions message={message} previousMessage={previousMessage} />
                </>
            )}
        </>
    )
}

function AnswerActions({
    message,
    previousMessage,
}: {
    message: ThreadMessage & { content: TrendGenerationResult }
    previousMessage: ThreadMessage
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
            answer: message.content,
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
            answer: message.content,
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
                    role="assistant"
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
