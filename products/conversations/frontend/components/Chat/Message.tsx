import { JSONContent } from '@tiptap/core'
import { useRef, useState } from 'react'

import {
    IconCopy,
    IconPencil,
    IconThumbsDown,
    IconThumbsDownFilled,
    IconThumbsUp,
    IconThumbsUpFilled,
    IconTrash,
    IconWarning,
} from '@posthog/icons'
import { LemonButton, LemonInput, ProfilePicture, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import type { AiReplyFeedbackRating, ChatMessage, MessageDeliveryStatus } from '../../types'
import { SupportMarkdown, SupportRichContentPreview } from '../Editor'
import { richContentToHtml } from '../Editor/richContentToHtml'
import { TeamOnlyBadge } from './TeamOnlyBadge'

export interface MessageProps {
    message: ChatMessage
    isCustomer: boolean
    deliveryStatus?: MessageDeliveryStatus
    showAiReplyFeedback?: boolean
    aiReplyFeedbackRating?: AiReplyFeedbackRating | null
    aiReplyFeedbackDisabledReason?: string
    onSubmitAiReplyFeedback?: (rating: AiReplyFeedbackRating, feedbackText?: string) => void
    onEdit?: () => void
    onDelete?: () => void
}

export function Message({
    message,
    isCustomer,
    deliveryStatus,
    showAiReplyFeedback = false,
    aiReplyFeedbackRating = null,
    aiReplyFeedbackDisabledReason,
    onSubmitAiReplyFeedback,
    onEdit,
    onDelete,
}: MessageProps): JSX.Element {
    const isAgent = message.authorType === 'AI'
    const profileType = isAgent ? 'bot' : 'person'
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
        if (aiReplyFeedbackDisabledReason || aiReplyFeedbackRating || !onSubmitAiReplyFeedback) {
            return
        }
        onSubmitAiReplyFeedback(rating)
    }

    function copyMessage(): void {
        // Generated on demand rather than per render, since only a copy needs it.
        const html = richContentToHtml(message.richContent as JSONContent | null)
        void copyToClipboard(message.content, 'Message', { html: html ?? undefined })
    }

    function submitBadFeedbackText(): void {
        if (aiReplyFeedbackDisabledReason || !feedbackText.trim() || !onSubmitAiReplyFeedback) {
            return
        }
        onSubmitAiReplyFeedback('bad', feedbackText.trim())
        setFeedbackTextSubmitted(true)
    }

    return (
        <div className={`flex ${isCustomer ? 'mr-10' : 'flex-row-reverse ml-10'} mb-4`}>
            <div className="flex gap-2 min-w-0">
                <div className="flex flex-col min-w-0 items-start">
                    {/* The agent's byline takes the AI colour too, so the name, the badge and the
                        bubble all say the same thing. `ProfilePicture` puts `className` on the avatar,
                        where the robot glyph picks the colour up, and renders the name as a sibling —
                        so the name is coloured from this row rather than through the component. */}
                    <div
                        className={`flex items-center justify-between w-full gap-2 mb-1 ${
                            isAgent ? '[&_.profile-name]:text-ai' : ''
                        }`}
                    >
                        <ProfilePicture
                            size="sm"
                            user={message.createdBy}
                            name={message.authorName}
                            type={profileType}
                            showName={true}
                            className={isAgent ? 'text-ai' : undefined}
                        />
                        <div className="flex items-center gap-1.5">
                            {isPrivate && <TeamOnlyBadge label="Private note" tone={isAgent ? 'agent' : 'teammate'} />}
                            <span className="text-xs text-muted-alt">
                                <TZLabel time={message.createdAt} />
                                {(message.version ?? 0) > 0 ? ' (edited)' : null}
                            </span>
                        </div>
                    </div>
                    <div className="max-w-full min-w-80">
                        {/* A note the customer can't see is set apart by hue, and which hue says who
                            wrote it: the assistant's notes take the AI colour the rest of the app
                            uses for our own agents, a teammate's keep the warning amber. Scanning a
                            long thread, "a colleague left me this" and "software left me this" are
                            different enough to be worth telling apart before either is read. The
                            byline and the lock badge above follow the same colour, so one note is
                            one signal rather than three competing ones. */}
                        <div
                            className={`border py-2 px-3 rounded-lg ${
                                isPrivate
                                    ? isAgent
                                        ? // The fills are the app's existing AI pair; the border is
                                          // held back to 60% because `border-ai` at full strength
                                          // outshouts the amber it sits next to, and the assistant
                                          // leaves one of these on nearly every ticket.
                                          'bg-ai/08 dark:bg-ai/20 border-ai/60'
                                        : 'bg-warning-highlight border-warning'
                                    : isCustomer
                                      ? 'bg-surface-secondary'
                                      : 'bg-surface-primary'
                            } [&_img]:max-h-64 [&_.SupportEditor__image]:max-h-64`}
                        >
                            {isPrivate && (
                                <div className="flex items-center justify-end gap-2">
                                    {onEdit && (
                                        <Tooltip title="Edit note">
                                            <LemonButton
                                                size="xsmall"
                                                icon={<IconPencil />}
                                                noPadding
                                                onClick={onEdit}
                                            />
                                        </Tooltip>
                                    )}
                                    {onDelete && (
                                        <Tooltip title="Delete note">
                                            <LemonButton
                                                size="xsmall"
                                                icon={<IconTrash />}
                                                noPadding
                                                status="danger"
                                                onClick={onDelete}
                                            />
                                        </Tooltip>
                                    )}
                                    <Tooltip title="Copy message">
                                        <LemonButton
                                            size="xsmall"
                                            icon={<IconCopy />}
                                            noPadding
                                            onClick={copyMessage}
                                        />
                                    </Tooltip>
                                </div>
                            )}
                            {/* Every message here is untrusted: customers write them, imports carry them,
                                and agents generate them from customer text. An inline remote image would
                                fetch on open, leaking the reader's IP or probing hosts their browser can
                                reach. PostHog-hosted images (attachments included) still render inline;
                                anything else becomes a click-to-open link. */}
                            {message.richContent ? (
                                <SupportRichContentPreview
                                    content={message.richContent as JSONContent}
                                    className="text-sm"
                                    fallbackContent={message.content}
                                    fallbackDisableImages={message.fromZendesk}
                                />
                            ) : (
                                <SupportMarkdown className="text-sm" disableImages>
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
                                                aiReplyFeedbackDisabledReason ??
                                                (aiReplyFeedbackRating ? 'Feedback already recorded' : undefined)
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
                                                aiReplyFeedbackDisabledReason ??
                                                (aiReplyFeedbackRating ? 'Feedback already recorded' : undefined)
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
                                            disabledReason={aiReplyFeedbackDisabledReason}
                                            autoFocus
                                        />
                                        <LemonButton
                                            type="primary"
                                            size="small"
                                            onClick={submitBadFeedbackText}
                                            disabledReason={
                                                aiReplyFeedbackDisabledReason ??
                                                (!feedbackText.trim() ? 'Please type a few words' : undefined)
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
