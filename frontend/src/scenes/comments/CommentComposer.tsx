import { LemonButton, LemonTextAreaMarkdown } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { commentsLogic, CommentsLogicProps } from './commentsLogic'

export const CommentComposer = (props: CommentsLogicProps): JSX.Element => {
    const { composedComment, commentsLoading, replyingCommentId } = useValues(commentsLogic(props))
    const { setComposedComment, sendComposedContent, setReplyingComment } = useActions(commentsLogic(props))

    const placeholder = replyingCommentId
        ? 'Reply...'
        : props.scope !== 'Misc'
        ? `Comment on ${props.scope}/${props.item_id ?? 'general'}`
        : props.item_id
        ? `Comment on ${props.item_id}`
        : `Comment`

    const ref = useRef<HTMLTextAreaElement>(null)

    useEffect(() => {
        if (replyingCommentId) {
            ref.current?.focus()
        }
    }, [replyingCommentId])

    return (
        <div className="space-y-2">
            <LemonTextAreaMarkdown
                data-attr={'comment-composer'}
                placeholder={placeholder}
                value={composedComment}
                onChange={setComposedComment}
                disabled={commentsLoading}
                onPressCmdEnter={sendComposedContent}
                ref={ref}
            />
            <div className="flex justify-between items-center gap-2">
                <div className="flex-1" />
                {replyingCommentId ? (
                    <LemonButton type="secondary" onClick={() => setReplyingComment(null)}>
                        Cancel reply
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
