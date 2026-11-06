import { useActions } from 'kea'

import {
    IconCopy,
    IconEye,
    IconRefresh,
    IconThumbsDown,
    IconThumbsDownFilled,
    IconThumbsUp,
    IconThumbsUpFilled,
    IconX,
} from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { copyToClipboard } from '~/lib/utils/copyToClipboard'
import { stripMarkdown } from '~/lib/utils/markdown'

import { MessageTemplate, useQuillThread } from 'products/posthog_ai/frontend/api/primitives'

import { maxThreadLogic } from '../maxThreadLogic'
import { QuillSuccessActions } from './quill/QuillSuccessActions'
import { useAnswerRating } from './useAnswerRating'

export interface SuccessActionsProps {
    retriable: boolean
    hideRatingAndRetry?: boolean
    content?: string | null
}

export function SuccessActions(props: SuccessActionsProps): JSX.Element {
    return useQuillThread() ? <QuillSuccessActions {...props} /> : <LemonSuccessActions {...props} />
}

function LemonSuccessActions({ retriable, hideRatingAndRetry, content }: SuccessActionsProps): JSX.Element {
    const { retryLastMessage } = useActions(maxThreadLogic)
    const {
        traceId,
        rating,
        submitRating,
        feedback,
        setFeedback,
        feedbackInputStatus,
        closeFeedback,
        submitFeedback,
        traceUrl,
    } = useAnswerRating()

    return (
        <>
            <div className="flex items-center ml-1">
                {content && (
                    <LemonButton
                        icon={<IconCopy />}
                        type="tertiary"
                        size="xsmall"
                        tooltip="Copy answer"
                        onClick={() => copyToClipboard(stripMarkdown(content))}
                    />
                )}
                {!hideRatingAndRetry && rating !== 'bad' && (
                    <LemonButton
                        icon={rating === 'good' ? <IconThumbsUpFilled /> : <IconThumbsUp />}
                        type="tertiary"
                        size="xsmall"
                        tooltip="Good answer"
                        onClick={() => submitRating('good')}
                    />
                )}
                {!hideRatingAndRetry && rating !== 'good' && (
                    <LemonButton
                        icon={rating === 'bad' ? <IconThumbsDownFilled /> : <IconThumbsDown />}
                        type="tertiary"
                        size="xsmall"
                        tooltip="Bad answer"
                        onClick={() => submitRating('bad')}
                    />
                )}
                {!hideRatingAndRetry && retriable && (
                    <LemonButton
                        icon={<IconRefresh />}
                        type="tertiary"
                        size="xsmall"
                        tooltip="Try again"
                        onClick={() => retryLastMessage()}
                    />
                )}
                {traceUrl && traceId && (
                    <LemonButton
                        to={traceUrl}
                        icon={<IconEye />}
                        type="tertiary"
                        size="xsmall"
                        tooltip="View trace in AI observability"
                    />
                )}
            </div>
            {!hideRatingAndRetry && feedbackInputStatus !== 'hidden' && (
                <MessageTemplate type="ai">
                    <div className="flex items-center gap-1">
                        <h4 className="m-0 text-sm grow">
                            {feedbackInputStatus === 'pending'
                                ? 'What disappointed you about the answer?'
                                : 'Thank you for your feedback!'}
                        </h4>
                        <LemonButton icon={<IconX />} type="tertiary" size="xsmall" onClick={closeFeedback} />
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
