import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { humanizeScope } from 'lib/components/ActivityLog/humanizeActivity'
import { LemonRichContentEditor } from 'lib/lemon-ui/LemonRichContent/LemonRichContentEditor'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { CommentsLogicProps, commentsLogic } from './commentsLogic'

export const CommentComposer = (props: CommentsLogicProps): JSX.Element => {
    const { key, commentsLoading, replyingCommentId, itemContext, isEmpty } = useValues(commentsLogic(props))
    const {
        sendComposedContent,
        setReplyingComment,
        clearItemContext,
        setRichContentEditor,
        onRichContentEditorUpdate,
    } = useActions(commentsLogic(props))

    const placeholder = replyingCommentId
        ? 'Reply...'
        : `Comment on ${props.item_id ? 'this ' : ''}${humanizeScope(props.scope, !!props.item_id)}`

    useEffect(() => {
        // Whenever the discussion context changes or we fully unmount we clear the item context
        return () => clearItemContext()
        // oxlint-disable-next-line exhaustive-deps
    }, [key, clearItemContext])

    return (
        <div className="deprecated-space-y-2">
            <LemonRichContentEditor
                logicKey="discussions"
                placeholder={placeholder}
                onCreate={setRichContentEditor}
                onUpdate={onRichContentEditorUpdate}
                onPressCmdEnter={sendComposedContent}
                disabled={commentsLoading}
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
                    disabledReason={isEmpty ? 'No message' : null}
                    sideIcon={<KeyboardShortcut command enter />}
                    data-attr="discussions-comment"
                >
                    Add {replyingCommentId ? 'reply' : 'comment'}
                </LemonButton>
            </div>
        </div>
    )
}
