import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { PhonePairHogs } from 'lib/components/hedgehogs'

import { CommentWithReplies } from './Comment'
import { CommentsLogicProps, commentsLogic } from './commentsLogic'

export const CommentsList = (props: CommentsLogicProps): JSX.Element => {
    const { key, commentsWithReplies, commentsLoading } = useValues(commentsLogic(props))
    const { loadComments } = useActions(commentsLogic(props))

    // If the comment list focus changes we should load the comments
    useEffect(() => {
        loadComments()
    }, [key]) // oxlint-disable-line react-hooks/exhaustive-deps

    return (
        <BindLogic logic={commentsLogic} props={props}>
            <div className="flex flex-col">
                {!commentsWithReplies?.length && commentsLoading ? (
                    <div className="deprecated-space-y-2">
                        <LemonSkeleton className="h-10 w-full" />
                    </div>
                ) : !commentsWithReplies?.length ? (
                    <div className="mx-auto p-8 max-w-160 mt-8 deprecated-space-y-4">
                        <div className="max-w-120 mx-auto">
                            <PhonePairHogs className="w-full h-full" />
                        </div>
                        <h2>Start the discussion!</h2>
                        <p>
                            You can add comments about this page for your team members to see. Great for sharing context
                            or ideas without getting in the way of the thing you are commenting on
                        </p>
                    </div>
                ) : null}

                <div className="deprecated-space-y-2">
                    {commentsWithReplies?.map((x) => (
                        <CommentWithReplies key={x.id} commentWithReplies={x} />
                    ))}
                </div>
            </div>
        </BindLogic>
    )
}
