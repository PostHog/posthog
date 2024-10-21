import { IconThumbsDown, IconThumbsDownFilled, IconThumbsUp, IconThumbsUpFilled, IconX } from '@posthog/icons'
import { LemonButton, LemonInput, Spinner } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useValues } from 'kea'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import posthog from 'posthog-js'
import React, { useRef, useState } from 'react'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { AssistantMessage, InsightQueryNode, InsightVizNode, NodeKind } from '~/queries/schema'

import { maxLogic, ThreadMessage } from './maxLogic'
import { isVisualizationMessage, parseVisualizationMessageContent } from './utils'

export function Thread(): JSX.Element | null {
    const { thread, threadLoading } = useValues(maxLogic)

    return (
        <div className="flex flex-col items-stretch w-full max-w-200 self-center gap-2 grow m-4">
            {thread.map((message, index) => {
                if (message.type === 'human') {
                    return (
                        <Message
                            key={index}
                            type={message.type}
                            className={message.status === 'error' ? 'border-danger' : undefined}
                        >
                            {message.content || <i>No text</i>}
                        </Message>
                    )
                }

                if (message.type === 'ai' && isVisualizationMessage(message.payload)) {
                    return <Answer key={index} message={message} previousMessage={thread[index - 1]} />
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

const Message = React.forwardRef<
    HTMLDivElement,
    React.PropsWithChildren<{ type: AssistantMessage['type']; className?: string }>
>(function Message({ type, children, className }, ref): JSX.Element {
    if (type === 'human') {
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

function Answer({ message, previousMessage }: { message: ThreadMessage; previousMessage: ThreadMessage }): JSX.Element {
    const { reasoning_steps, answer } = parseVisualizationMessageContent(message.content)

    const query = {
        kind: NodeKind.InsightVizNode,
        source: answer,
    }

    return (
        <>
            {reasoning_steps && (
                <Message type={message.type}>
                    <ul className="list-disc ml-4">
                        {reasoning_steps.map((step, index) => (
                            <li key={index}>{step}</li>
                        ))}
                    </ul>
                </Message>
            )}
            {message.status === 'completed' && answer && (
                <>
                    <Message type={message.type}>
                        <div className="h-96 flex">
                            <Query query={query} readOnly embedded />
                        </div>
                        <LemonButton
                            className="mt-4 w-fit"
                            type="primary"
                            to={urls.insightNew(undefined, undefined, {
                                kind: NodeKind.InsightVizNode,
                                source: answer as InsightQueryNode,
                            } as InsightVizNode)}
                            sideIcon={<IconOpenInNew />}
                            targetBlank
                        >
                            Open as new insight
                        </LemonButton>
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
    message: ThreadMessage
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
