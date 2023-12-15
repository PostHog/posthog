import { LemonSkeleton } from '@posthog/lemon-ui'
import { BindLogic, useValues } from 'kea'

import { CommentWithReplies } from './Comment'
import { commentsLogic, CommentsLogicProps } from './commentsLogic'

export const CommentsList = (props: CommentsLogicProps): JSX.Element => {
    const { commentsWithReplies, commentsLoading } = useValues(commentsLogic(props))

    return (
        <BindLogic logic={commentsLogic} props={props}>
            <div className="flex flex-col">
                {!commentsWithReplies?.length && commentsLoading ? (
                    <div className="space-y-2">
                        <LemonSkeleton className="h-10 w-full" />
                    </div>
                ) : !commentsWithReplies?.length ? (
                    <div className="rounded p-4 text-center">No discussion here yet...</div>
                ) : null}

                <div className="space-y-2">
                    {commentsWithReplies?.map((x) => (
                        <CommentWithReplies key={x.id} commentWithReplies={x} />
                    ))}
                </div>
            </div>
        </BindLogic>
    )
}
