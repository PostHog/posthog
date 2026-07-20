import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { humanizeScope } from 'lib/components/ActivityLog/humanizeActivity'
import { KeyboardShortcut } from 'lib/components/KeyboardShortcut/KeyboardShortcut'
import { LemonRichContentEditor } from 'lib/lemon-ui/LemonRichContent/LemonRichContentEditor'

import { CommentsLogicProps, commentsLogic } from './commentsLogic'

export type CommentComposerProps = CommentsLogicProps & {
    /** The footer variant hides itself while a reply is in progress; 'inline-reply' renders inside the thread */
    variant?: 'footer' | 'inline-reply'
}

export const CommentComposer = ({ variant = 'footer', ...props }: CommentComposerProps): JSX.Element | null => {
    const { key, commentsLoading, replyingCommentId, itemContext, isEmpty, composerDraft } = useValues(
        commentsLogic(props)
    )
    const { sendComposedContent, clearItemContext, setRichContentEditor, onRichContentEditorUpdate } = useActions(
        commentsLogic(props)
    )

    const placeholder = replyingCommentId
        ? 'Reply...'
        : `Comment on ${props.item_id ? 'this ' : ''}${humanizeScope(props.scope, !!props.item_id)}`

    useEffect(() => {
        // Only the footer owns the item context - the inline reply composer unmounting must not wipe it
        if (variant !== 'footer') {
            return
        }
        // Whenever the discussion context changes or we fully unmount we clear the item context
        return () => clearItemContext()
        // oxlint-disable-next-line exhaustive-deps
    }, [key, variant, clearItemContext])

    if (variant === 'footer' && replyingCommentId) {
        // The composer is rendered inline in the thread being replied to
        return null
    }

    const buttonSize = variant === 'inline-reply' ? 'small' : undefined

    return (
        <div className="flex flex-col gap-2">
            <LemonRichContentEditor
                key={key}
                logicKey="discussions"
                placeholder={placeholder}
                initialContent={composerDraft}
                onCreate={setRichContentEditor}
                onUpdate={onRichContentEditorUpdate}
                onPressCmdEnter={() => sendComposedContent(false)}
                disabled={commentsLoading}
            />
            <div className="flex justify-between items-center gap-2">
                <div className="flex-1" />
                {itemContext ? (
                    <LemonButton size={buttonSize} type="secondary" onClick={() => clearItemContext()}>
                        Cancel
                    </LemonButton>
                ) : null}
                {!replyingCommentId ? (
                    <LemonButton
                        size={buttonSize}
                        type="secondary"
                        onClick={() => sendComposedContent(true)}
                        loading={commentsLoading}
                        disabledReason={isEmpty ? 'No message' : null}
                        data-attr="discussions-comment-task"
                    >
                        Add as task
                    </LemonButton>
                ) : null}
                <LemonButton
                    size={buttonSize}
                    type="primary"
                    onClick={() => sendComposedContent(false)}
                    loading={commentsLoading}
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
