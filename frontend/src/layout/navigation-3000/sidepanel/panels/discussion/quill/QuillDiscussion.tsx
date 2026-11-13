import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconPlus } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { CommentsLogicProps, commentsLogic } from 'lib/components/Comments/commentsLogic'
import { SendCommentToSlackModal } from 'lib/components/Comments/SendCommentToSlackModal'

import { sidePanelStateLogic } from '../../../sidePanelStateLogic'
import { sidePanelDiscussionLogic } from '../sidePanelDiscussionLogic'
import { QuillCommentComposer } from './QuillCommentComposer'
import { QuillCommentThreads } from './QuillCommentThreads'

/** The threads about one object, with the composer for a new comment pinned below them. */
export function QuillDiscussion({ logicProps }: { logicProps: CommentsLogicProps }): JSX.Element {
    const { selectedTabOptions } = useValues(sidePanelStateLogic)
    const { setCommentsListRef } = useActions(sidePanelDiscussionLogic)
    const { key, replyingCommentId } = useValues(commentsLogic(logicProps))
    const { setSelectedComment, startNewComment, clearItemContext } = useActions(commentsLogic(logicProps))

    useEffect(() => {
        // A deep link selects its comment without focusing the composer, and opens the thread it sits in.
        setSelectedComment(selectedTabOptions ?? null, true)
    }, [selectedTabOptions]) // oxlint-disable-line react-hooks/exhaustive-deps

    // A comment anchored to part of the page belongs to that page, so leaving it or closing the panel drops the anchor.
    useEffect(() => () => clearItemContext(), [key, clearItemContext])

    return (
        <BindLogic logic={commentsLogic} props={logicProps}>
            <div className="flex min-h-0 flex-1 flex-col">
                <div
                    ref={setCommentsListRef}
                    className="min-h-0 flex-1 overflow-y-auto scroll-mask-y-4 scroll-py-4 px-1 py-3"
                    data-attr="discussions-threads"
                >
                    <QuillCommentThreads logicProps={logicProps} />
                </div>
                <div className="shrink-0 border-t border-border p-3">
                    {/* The reply composer sits in its thread, so the footer offers a way back to a new comment. */}
                    {replyingCommentId ? (
                        <Button
                            variant="outline"
                            className="w-full"
                            onClick={() => startNewComment()}
                            data-attr="discussions-new-comment"
                        >
                            <IconPlus />
                            New comment
                        </Button>
                    ) : (
                        <QuillCommentComposer logicProps={logicProps} />
                    )}
                </div>
            </div>
            <SendCommentToSlackModal />
        </BindLogic>
    )
}
