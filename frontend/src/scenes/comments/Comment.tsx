import { TZLabel } from '@posthog/apps-common'
import { ProfilePicture } from '@posthog/lemon-ui'

import { CommentType } from '~/types'

export type CommentProps = {
    comment: CommentType
}

export const Comment = ({ comment }: CommentProps): JSX.Element => {
    return (
        <div className="border rounded bg-bg-light flex justify-start p-2 gap-2 ">
            <ProfilePicture name={comment.created_by?.first_name} email={comment.created_by?.email} />

            <div className="flex flex-col flex-1">
                <div className="flex items-center justify-between gap-2">
                    <span className="font-semibold">{comment.created_by?.first_name ?? 'Unknown user'}</span>
                    {comment.created_at ? (
                        <span className="text-xs">
                            <TZLabel time={comment.created_at} />
                        </span>
                    ) : null}
                </div>
                <div>{comment.content}</div>
            </div>
        </div>
    )
}
