import { Avatar, AvatarFallback, AvatarImage } from '@posthog/quill'

import { getCommentAuthorName } from 'lib/components/Comments/commentUtils'
import { gravatarUrl } from 'lib/utils/gravatar'

import { CommentType } from '~/types'

export function QuillCommentAvatar({ comment, size }: { comment: CommentType; size: 'default' | 'xs' }): JSX.Element {
    const email = comment.created_by?.email

    return (
        <Avatar size={size}>
            {email && <AvatarImage src={gravatarUrl(email)} alt="" />}
            <AvatarFallback>{getCommentAuthorName(comment).slice(0, 1).toUpperCase()}</AvatarFallback>
        </Avatar>
    )
}
