import { useActions, useValues } from 'kea'

import {
    ThreadItemReaction,
    ThreadItemReactionEmoji,
    ThreadItemReactions,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { commentsLogic } from 'lib/components/Comments/commentsLogic'
import { pluralize } from 'lib/utils/strings'

import { CommentType } from '~/types'

export function QuillCommentReactions({ comment }: { comment: CommentType }): JSX.Element | null {
    const { emojiReactionsByComment, isMyComment } = useValues(commentsLogic)
    const { deleteComment, sendEmojiReaction } = useActions(commentsLogic)
    const reactions = Object.entries(emojiReactionsByComment[comment.id] ?? {})

    if (!reactions.length) {
        return null
    }

    return (
        <ThreadItemReactions data-attr="comment-reactions">
            {reactions.map(([emoji, reactionComments]) => {
                const myReaction = reactionComments.find((reaction) => isMyComment(reaction))
                const names = reactionComments.map((reaction) =>
                    isMyComment(reaction) ? 'You' : (reaction.created_by?.first_name ?? 'Unknown user')
                )
                return (
                    <Tooltip key={emoji}>
                        <TooltipTrigger
                            render={
                                <ThreadItemReaction
                                    pressed={!!myReaction}
                                    onPressedChange={() =>
                                        myReaction ? deleteComment(myReaction) : sendEmojiReaction(emoji, comment.id)
                                    }
                                    aria-label={`${emoji} ${pluralize(reactionComments.length, 'reaction')}`}
                                    data-attr={`comment-reaction-${emoji}`}
                                />
                            }
                        >
                            <ThreadItemReactionEmoji>{emoji}</ThreadItemReactionEmoji>
                            <span translate="no">{reactionComments.length}</span>
                        </TooltipTrigger>
                        <TooltipContent className="ph-no-capture">{names.join(', ')}</TooltipContent>
                    </Tooltip>
                )
            })}
        </ThreadItemReactions>
    )
}
