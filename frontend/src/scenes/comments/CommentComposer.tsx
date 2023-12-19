import { LemonButton, LemonTextAreaMarkdown } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { commentsLogic, CommentsLogicProps } from './commentsLogic'

export const CommentComposer = (props: CommentsLogicProps): JSX.Element => {
    const { key, composedComment, commentsLoading, replyingCommentId, itemContext } = useValues(commentsLogic(props))
    const { setComposedComment, sendComposedContent, setReplyingComment, setComposerRef, clearItemContext } =
        useActions(commentsLogic(props))

    const placeholder = replyingCommentId
        ? 'Reply...'
        : props.scope !== 'Misc'
        ? `Comment on ${props.scope}/${props.item_id ?? 'general'}`
        : props.item_id
        ? `Comment on ${props.item_id}`
        : `Comment`

    useEffect(() => {
        // Whenever the discussion context changes or we fully unmount we clear the item context
        return () => clearItemContext()
    }, [key])

    return (
        <div className="space-y-2">
            <LemonTextAreaMarkdown
                data-attr={'comment-composer'}
                placeholder={placeholder}
                value={composedComment}
                onChange={setComposedComment}
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
                    disabledReason={!composedComment ? 'No message' : null}
                    sideIcon={<KeyboardShortcut command enter />}
                >
                    Add {replyingCommentId ? 'reply' : 'comment'}
                </LemonButton>
            </div>
        </div>
    )
}
