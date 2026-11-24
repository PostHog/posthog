import { useActions, useValues } from 'kea'

import { IconComment, IconEllipsis, IconPencil, IconTrash } from '@posthog/icons'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    ThreadItemAction,
    ThreadItemActions,
} from '@posthog/quill'

import { commentsLogic } from 'lib/components/Comments/commentsLogic'
import { scopeSyncsToSlack } from 'lib/components/Comments/commentUtils'
import { sendCommentToSlackLogic } from 'lib/components/Comments/sendCommentToSlackLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconSlack } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { CommentType } from '~/types'

import { QuillEmojiPickerPopover } from './QuillEmojiPickerPopover'

/** The comment's hover toolbar: react, reply, and a menu for the rest. */
export function QuillCommentActions({ comment }: { comment: CommentType }): JSX.Element {
    const { disabledReasonFor, sendToSlackDisabledReasonFor } = useValues(commentsLogic)
    const { deleteComment, setEditingComment, sendEmojiReaction, setReplyingComment } = useActions(commentsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { openModal } = useActions(sendCommentToSlackLogic)

    // Only an untracked thread root can go to Slack. Replies follow their parent.
    const canSendToSlack =
        !!featureFlags[FEATURE_FLAGS.DISCUSSIONS_SLACK_SYNC] &&
        scopeSyncsToSlack(comment.scope) &&
        !comment.source_comment &&
        !comment.item_context?.from_slack &&
        !comment.slack_thread

    return (
        // The toolbar shows on hover, so it stays shown while one of its menus is open.
        <ThreadItemActions
            aria-label="Comment actions"
            className="has-[[data-popup-open]]:pointer-events-auto has-[[data-popup-open]]:opacity-100"
        >
            <QuillEmojiPickerPopover
                onSelect={(emoji) => sendEmojiReaction(emoji, comment.id)}
                trigger={<ThreadItemAction label="Add reaction" data-attr="comment-react-button" />}
            />
            <ThreadItemAction
                label="Reply in thread"
                onClick={() => setReplyingComment(comment.source_comment ?? comment.id)}
                data-attr="comment-reply-button"
            >
                <IconComment />
            </ThreadItemAction>
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={<ThreadItemAction label="More actions" data-attr="comment-more-actions" />}
                >
                    <IconEllipsis />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                    {canSendToSlack && (
                        <DropdownMenuItem
                            onClick={() => openModal(comment)}
                            disabledReason={sendToSlackDisabledReasonFor(comment)}
                            data-attr="comment-send-to-slack"
                        >
                            <IconSlack />
                            Send to Slack
                        </DropdownMenuItem>
                    )}
                    <DropdownMenuItem onClick={() => setEditingComment(comment)} data-attr="comment-edit">
                        <IconPencil />
                        Edit
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                        variant="destructive"
                        onClick={() => deleteComment(comment)}
                        disabledReason={disabledReasonFor(comment)}
                        data-attr="comment-delete"
                    >
                        <IconTrash />
                        Delete
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>
        </ThreadItemActions>
    )
}
