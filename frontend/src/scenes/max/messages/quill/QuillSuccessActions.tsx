import { useActions } from 'kea'

import {
    IconEye,
    IconRefresh,
    IconThumbsDown,
    IconThumbsDownFilled,
    IconThumbsUp,
    IconThumbsUpFilled,
    IconX,
} from '@posthog/icons'
import { Button, ChatMessageFooter, Input, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { stripMarkdown } from '~/lib/utils/markdown'

import { QuillCopyButton, QuillFooterButton } from 'products/posthog_ai/frontend/api/primitives'

import { maxThreadLogic } from '../../maxThreadLogic'
import type { SuccessActionsProps } from '../SuccessActions'
import { useAnswerRating } from '../useAnswerRating'

/** The quill answer footer: the same affordances as the lemon row, drawn like a sandbox turn's footer. */
export function QuillSuccessActions({ retriable, hideRatingAndRetry, content }: SuccessActionsProps): JSX.Element {
    const { retryLastMessage } = useActions(maxThreadLogic)
    const {
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
        <div className="flex flex-col gap-2">
            <ChatMessageFooter className="min-h-5 items-center gap-1 ps-0">
                {content && <QuillCopyButton value={stripMarkdown(content)} label="Copy answer" />}
                {!hideRatingAndRetry && rating !== 'bad' && (
                    <QuillFooterButton label="Good answer" onClick={() => submitRating('good')}>
                        {rating === 'good' ? <IconThumbsUpFilled /> : <IconThumbsUp />}
                    </QuillFooterButton>
                )}
                {!hideRatingAndRetry && rating !== 'good' && (
                    <QuillFooterButton label="Bad answer" onClick={() => submitRating('bad')}>
                        {rating === 'bad' ? <IconThumbsDownFilled /> : <IconThumbsDown />}
                    </QuillFooterButton>
                )}
                {!hideRatingAndRetry && retriable && (
                    <QuillFooterButton label="Try again" onClick={() => retryLastMessage()}>
                        <IconRefresh />
                    </QuillFooterButton>
                )}
                {traceUrl && (
                    <Button
                        variant="default"
                        size="icon-xs"
                        aria-label="View trace in AI observability"
                        tooltip="View trace in AI observability"
                        className="text-muted-foreground hover:text-foreground"
                        render={<LinkPrimitive to={traceUrl} />}
                    >
                        <IconEye />
                    </Button>
                )}
            </ChatMessageFooter>
            {!hideRatingAndRetry && feedbackInputStatus !== 'hidden' && (
                <div className="flex max-w-4/5 flex-col gap-2 rounded-lg border border-border p-3">
                    <div className="flex items-center gap-1">
                        <Text size="sm" weight="medium" className="grow">
                            {feedbackInputStatus === 'pending'
                                ? 'What disappointed you about the answer?'
                                : 'Thank you for your feedback!'}
                        </Text>
                        <QuillFooterButton label="Close" onClick={closeFeedback}>
                            <IconX />
                        </QuillFooterButton>
                    </div>
                    {feedbackInputStatus === 'pending' && (
                        <form
                            className="flex items-center gap-1.5"
                            onSubmit={(event) => {
                                event.preventDefault()
                                submitFeedback()
                            }}
                        >
                            <Input
                                aria-label="What disappointed you about the answer?"
                                placeholder="Help us improve PostHog AI…"
                                value={feedback}
                                onChange={(event) => setFeedback(event.target.value)}
                                autoFocus
                            />
                            <Button
                                type="submit"
                                variant="primary"
                                disabledReason={!feedback ? 'Please type a few words!' : undefined}
                            >
                                Submit
                            </Button>
                        </form>
                    )}
                </div>
            )}
        </div>
    )
}
