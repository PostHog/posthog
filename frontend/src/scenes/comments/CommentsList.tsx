import { LemonSkeleton } from '@posthog/lemon-ui'
import { useValues } from 'kea'

import { Comment } from './Comment'
import { commentsLogic, CommentsLogicProps } from './commentsLogic'

export const CommentsList = (props: CommentsLogicProps): JSX.Element => {
    const { comments, commentsLoading } = useValues(commentsLogic(props))

    return (
        <div className="flex flex-col">
            {!comments?.length && commentsLoading ? (
                <div className="space-y-2">
                    <LemonSkeleton className="h-10 w-full" />
                </div>
            ) : !comments?.length ? (
                <div className="rounded p-4 text-center">No discussion here yet...</div>
            ) : null}

            <div className="space-y-2">
                {comments?.map((x) => (
                    <Comment key={x.id} comment={x} />
                ))}
            </div>
        </div>
    )
}
