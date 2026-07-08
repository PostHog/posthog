import { JSONContent } from '@tiptap/core'
import { useRef, useState } from 'react'

import {
    IconCopy,
    IconLock,
    IconThumbsDown,
    IconThumbsDownFilled,
    IconThumbsUp,
    IconThumbsUpFilled,
    IconWarning,
} from '@posthog/icons'
import { LemonButton, LemonInput, ProfilePicture, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import type { AiReplyFeedbackRating, ChatMessage, MessageDeliveryStatus } from '../../types'
import { SupportMarkdown, SupportRichContentPreview } from '../Editor'

export interface MessageProps {
    message: ChatMessage
    isCustomer: boolean
    deliveryStatus?: MessageDeliveryStatus
    showAiReplyFeedback?: boolean
    aiReplyFeedbackRating?: AiReplyFeedbackRating | null
    onSubmitAiReplyFeedback?: (rating: AiReplyFeedbackRating, feedbackText?: string) => void
}

export function Message({
    message,
    isCustomer,
    deliveryStatus,
    showAiReplyFeedback = false,
    aiReplyFeedbackRating = null,
    onSubmitAiReplyFeedback,
}: MessageProps): JSX.Element {
    const profileType = message.authorType === 'AI' ? 'bot' : 'person'
    const isPrivate = message.isPrivate
    const [feedbackText, setFeedbackText] = useState('')
    const [feedbackTextSubmitted, setFeedbackTextSubmitted] = useState(false)
    const wasRatedOnMount = useRef(!!aiReplyFeedbackRating)
    const showBadFeedbackInput =
        showAiReplyFeedback &&
        aiReplyFeedbackRating === 'bad' &&
        !wasRatedOnMount.current &&
        !feedbackTextSubmitted &&
        !!onSubmitAiReplyFeedback

    function submitRating(rating: AiReplyFeedbackRating): void {
        if (aiReplyFeedbackRating || !onSubmitAiReplyFeedback) {
            return
        }
        onSubmitAiReplyFeedback(rating)
    }

    function submitBadFeedbackText(): void {
        if (!feedbackText.trim() || !onSubmitAiReplyFeedback) {
            return
        }
        onSubmitAiReplyFeedback('bad', feedbackText.trim())
        setFeedbackTextSubmitted(true)
    }

    return (
        <div className={`flex ${isCustomer ? 'mr-10' : 'flex-row-reverse ml-10'} mb-4`}>
            <div className="flex gap-2">
                <div className="flex flex-col min-w-0 items-start">
                    <div className="flex items-center justify-between w-full gap-2 mb-1">
                        <ProfilePicture
                            size="sm"
                            user={message.createdBy}
                            name={message.authorName}
                            type={profileType}
                            showName={true}
                        />
                        <div className="flex items-center gap-1.5">
                            {isPrivate && (
                                <Tooltip title="Only visible to your team">
                                    <span className="inline-flex items-center gap-0.5 text-xs text-warning-dark bg-warning-highlight px-1.5 py-0.5 rounded">
                                        <IconLock className="text-xs" />
                                        Private note
                                    </span>
                                </Tooltip>
                            )}
                            <span className="text-xs text-muted-alt">
                                <TZLabel time={message.createdAt} />
                            </span>
                        </div>
                    </div>
                    <div className="max-w-full min-w-80">
                        <div
                            className={`border py-2 px-3 rounded-lg ${
                                isPrivate ? 'bg-warning-highlight border-warning' : 'bg-surface-primary'
                            } [&_img]:max-h-64 [&_.SupportEditor__image]:max-h-64`}
                        >
                            {isPrivate && (
                                <div className="flex items-center justify-end">
                                    <Tooltip title="Copy message">
                                        <LemonButton
                                            size="xsmall"
                                            icon={<IconCopy />}
                                            noPadding
                                            onClick={() => void copyToClipboard(message.content, 'Message')}
                                        />
                                    </Tooltip>
                                </div>
                            )}
                            {message.richContent ? (
                                <SupportRichContentPreview
                                    content={message.richContent as JSONContent}
                                    className="text-sm"
                                />
                            ) : (
                                <SupportMarkdown className="text-sm" disableImages={message.fromZendesk}>
                                    {message.content}
                                </SupportMarkdown>
                            )}
                        </div>
                        {showAiReplyFeedback && (
                            <div className="mt-1.5 space-y-1.5">
                                <div className="flex items-center gap-1">
                                    {aiReplyFeedbackRating !== 'bad' && (
                                        <LemonButton
                                            icon={
                                                aiReplyFeedbackRating === 'good' ? (
                                                    <IconThumbsUpFilled />
                                                ) : (
                                                    <IconThumbsUp />
                                                )
                                            }
                                            type="tertiary"
                                            size="xsmall"
                                            tooltip="Good reply"
                                            disabledReason={
                                                aiReplyFeedbackRating ? 'Feedback already recorded' : undefined
                                            }
                                            onClick={() => submitRating('good')}
                                            data-attr="ai-reply-feedback-good"
                                        />
                                    )}
                                    {aiReplyFeedbackRating !== 'good' && (
                                        <LemonButton
                                            icon={
                                                aiReplyFeedbackRating === 'bad' ? (
                                                    <IconThumbsDownFilled />
                                                ) : (
                                                    <IconThumbsDown />
                                                )
                                            }
                                            type="tertiary"
                                            size="xsmall"
                                            tooltip="Bad reply"
                                            disabledReason={
                                                aiReplyFeedbackRating ? 'Feedback already recorded' : undefined
                                            }
                                            onClick={() => submitRating('bad')}
                                            data-attr="ai-reply-feedback-bad"
                                        />
                                    )}
                                </div>
                                {showBadFeedbackInput && (
                                    <div className="flex w-full gap-1.5 items-center">
                                        <LemonInput
                                            placeholder="What was wrong with this reply?"
                                            fullWidth
                                            size="small"
                                            value={feedbackText}
                                            onChange={setFeedbackText}
                                            onPressEnter={submitBadFeedbackText}
                                            autoFocus
                                        />
                                        <LemonButton
                                            type="primary"
                                            size="small"
                                            onClick={submitBadFeedbackText}
                                            disabledReason={
                                                !feedbackText.trim() ? 'Please type a few words' : undefined
                                            }
                                        >
                                            Submit
                                        </LemonButton>
                                    </div>
                                )}
                                {aiReplyFeedbackRating === 'bad' && feedbackTextSubmitted && (
                                    <span className="text-xs text-muted-alt">Thanks for your feedback</span>
                                )}
                            </div>
                        )}
                        <div className="flex items-center justify-end gap-1">
                            {message.emailDeliveryStatus === 'failed' ? (
                                <Tooltip title="We couldn't deliver this email reply. Please check the email channel settings and contact support if the issue persists.">
                                    <span className="inline-flex items-center gap-0.5 text-xs text-danger">
                                        <IconWarning className="text-xs" />
                                        Failed to send
                                    </span>
                                </Tooltip>
                            ) : message.emailDeliveryStatus === 'sending' ? (
                                <span className="text-xs text-muted-alt">Sending…</span>
                            ) : (
                                deliveryStatus && (
                                    <span className="text-xs text-muted-alt">
                                        {deliveryStatus === 'read' ? 'Read' : 'Sent'}
                                    </span>
                                )
                            )}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}
