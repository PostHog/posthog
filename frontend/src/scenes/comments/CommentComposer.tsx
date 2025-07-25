import { LemonButton, LemonTipTapMarkdown } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { humanizeScope } from 'lib/components/ActivityLog/humanizeActivity'
import { useEffect } from 'react'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { commentsLogic, CommentsLogicProps } from './commentsLogic'

export const CommentComposer = (props: CommentsLogicProps): JSX.Element => {
    const { key, composedComment, composedRichContent, commentsLoading, replyingCommentId, itemContext } = useValues(
        commentsLogic(props)
    )
    const {
        setComposedComment,
        setComposedRichContent,
        sendComposedContent,
        setReplyingComment,
        setComposerRef,
        clearItemContext,
    } = useActions(commentsLogic(props))

    const placeholder = replyingCommentId
        ? 'Reply...'
        : `Comment on ${props.item_id ? 'this ' : ''}${humanizeScope(props.scope, !!props.item_id)}`

    useEffect(() => {
        // Whenever the discussion context changes or we fully unmount we clear the item context
        return () => clearItemContext()
    }, [key])

    return (
        <div className="deprecated-space-y-2">
            <LemonTipTapMarkdown
                data-attr="comment-composer"
                placeholder={placeholder}
                value={composedComment}
                richContent={composedRichContent}
                onChange={setComposedComment}
                onRichContentChange={setComposedRichContent}
                disabled={commentsLoading}
                onPressCmdEnter={sendComposedContent}
                ref={setComposerRef}
            />
            <div className="flex justify-between items-center gap-2">
                <div className="flex-1" />
                {replyingCommentId ? (
                    <LemonButton type="secondary" onClick={() => setReplyingComment(null)}>
                        Cancel reply
                    </LemonButton>
                ) : null}
                {itemContext ? (
                    <LemonButton type="secondary" onClick={() => clearItemContext()}>
                        Cancel
                    </LemonButton>
                ) : null}
                <LemonButton
                    type="primary"
                    onClick={sendComposedContent}
                    disabledReason={!composedComment && !composedRichContent ? 'No message' : null}
                    sideIcon={<KeyboardShortcut command enter />}
                    data-attr="discussions-comment"
                >
                    Add {replyingCommentId ? 'reply' : 'comment'}
                </LemonButton>
            </div>
        </div>
    )
}
