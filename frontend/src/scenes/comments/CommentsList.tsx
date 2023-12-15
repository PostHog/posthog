import { LemonSkeleton } from '@posthog/lemon-ui'
import { BindLogic, useValues } from 'kea'

import { Comment } from './Comment'
import { commentsLogic, CommentsLogicProps } from './commentsLogic'

export const CommentsList = (props: CommentsLogicProps): JSX.Element => {
    const { sortedComments, commentsLoading } = useValues(commentsLogic(props))

    return (
        <BindLogic logic={commentsLogic} props={props}>
            <div className="flex flex-col">
                {!sortedComments?.length && commentsLoading ? (
                    <div className="space-y-2">
                        <LemonSkeleton className="h-10 w-full" />
                    </div>
                ) : !sortedComments?.length ? (
                    <div className="rounded p-4 text-center">No discussion here yet...</div>
                ) : null}

                <div className="space-y-2">
                    {sortedComments?.map((x) => (
                        <Comment key={x.id} comment={x} />
                    ))}
                </div>
            </div>
        </BindLogic>
    )
}
