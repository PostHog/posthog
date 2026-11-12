import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { IconChat, IconWarning } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Skeleton,
} from '@posthog/quill'

import { humanizeScope } from 'lib/components/ActivityLog/humanizeActivity'
import { CommentsLogicProps, commentsLogic } from 'lib/components/Comments/commentsLogic'

import { getContinuationIds } from './commentGrouping'
import { QuillCommentThread } from './QuillCommentThread'

export function QuillCommentThreads({ logicProps }: { logicProps: CommentsLogicProps }): JSX.Element {
    const { key, comments, commentsWithReplies, commentsLoadFailed, commentsLoading, expandedThreadIds } =
        useValues(commentsLogic)
    const { loadComments, setReplyingComment, clearRichContentEditor } = useActions(commentsLogic)

    const continuationIds = useMemo(
        () => getContinuationIds(commentsWithReplies, expandedThreadIds),
        [commentsWithReplies, expandedThreadIds]
    )

    useEffect(() => {
        loadComments()
    }, [key]) // oxlint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        return () => {
            // Closing the panel ends any reply, so it opens fresh next time. The reply text stays in its thread's
            // draft. Clearing the editor also stops anything waiting for a composer from taking the dying one.
            setReplyingComment(null)
            clearRichContentEditor()
        }
    }, []) // oxlint-disable-line react-hooks/exhaustive-deps

    if (!comments) {
        if (commentsLoadFailed && !commentsLoading) {
            return (
                <Empty>
                    <EmptyHeader>
                        <EmptyMedia variant="icon">
                            <IconWarning />
                        </EmptyMedia>
                        <EmptyTitle>Comments didn't load</EmptyTitle>
                        <EmptyDescription>Check your connection and try again.</EmptyDescription>
                    </EmptyHeader>
                    <EmptyContent>
                        <Button variant="outline" onClick={() => loadComments()} data-attr="discussions-retry">
                            Try again
                        </Button>
                    </EmptyContent>
                </Empty>
            )
        }
        return (
            <div className="flex flex-col gap-2">
                {Array.from({ length: 3 }, (_, index) => (
                    <Skeleton key={index} className="h-16" />
                ))}
            </div>
        )
    }

    if (!commentsWithReplies.length) {
        const noun = `${logicProps.item_id ? 'this ' : ''}${humanizeScope(logicProps.scope, !!logicProps.item_id).toLowerCase()}`
        return (
            <Empty>
                <EmptyHeader>
                    <EmptyMedia variant="icon">
                        <IconChat />
                    </EmptyMedia>
                    <EmptyTitle>No comments yet</EmptyTitle>
                    <EmptyDescription>Comment on {noun} to share context or ideas with your team.</EmptyDescription>
                </EmptyHeader>
            </Empty>
        )
    }

    return (
        <div className="flex flex-col">
            {commentsWithReplies.map((thread) => (
                <QuillCommentThread
                    key={thread.id}
                    thread={thread}
                    logicProps={logicProps}
                    continuationIds={continuationIds}
                />
            ))}
        </div>
    )
}
