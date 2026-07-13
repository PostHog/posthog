import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import * as phoneCall from '@posthog/brand/hoggies/png/phone-call'
import { LemonSkeleton } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'

import { CommentWithReplies } from './Comment'
import { CommentsLogicProps, commentsLogic } from './commentsLogic'

const HedgehogPhoneCall = pngHoggie(phoneCall)

export interface CommentsListProps extends CommentsLogicProps {
    noun?: string
}

export const CommentsList = ({ noun = 'page', ...props }: CommentsListProps): JSX.Element => {
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
                    <div className="mx-auto p-8 max-w-160 deprecated-space-y-4">
                        <div className="max-w-120 mx-auto">
                            <HedgehogPhoneCall className="w-full max-w-[200px]" />
                        </div>
                        <h2>Start the discussion!</h2>
                        <p>
                            You can add comments about this {noun} for your team members to see. Great for sharing
                            context or ideas without getting in the way of the thing you are commenting on
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
