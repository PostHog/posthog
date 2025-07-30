import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { humanizeScope } from 'lib/components/ActivityLog/humanizeActivity'
import { useEffect } from 'react'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { commentsLogic, CommentsLogicProps } from './commentsLogic'
import { RichContentEditor } from 'lib/components/RichContentEditor'
import ExtensionDocument from '@tiptap/extension-document'
import ExtensionPlaceholder from '@tiptap/extension-placeholder'
import StarterKit from '@tiptap/starter-kit'
import { RichContentNodeMention } from 'lib/components/RichContentEditor/RichContentNodeMention'
import { MentionsExtension } from 'lib/components/RichContentEditor/MentionsExtension'
import { createEditor } from 'lib/components/RichContentEditor/utils'

export const CommentComposer = (props: CommentsLogicProps): JSX.Element => {
    const { key, composedComment, commentsLoading, replyingCommentId, itemContext } = useValues(commentsLogic(props))
    const { setComposedComment, sendComposedContent, setReplyingComment, setEditor, clearItemContext } = useActions(
        commentsLogic(props)
    )

    const placeholder = replyingCommentId
        ? 'Reply...'
        : `Comment on ${props.item_id ? 'this ' : ''}${humanizeScope(props.scope, !!props.item_id)}`

    useEffect(() => {
        // Whenever the discussion context changes or we fully unmount we clear the item context
        return () => clearItemContext()
        // oxlint-disable-next-line exhaustive-deps
    }, [key])

    return (
        <div className="deprecated-space-y-2">
            <RichContentEditor
                logicKey="Discussions"
                extensions={[
                    ExtensionDocument,
                    StarterKit.configure({
                        document: false,
                        gapcursor: false,
                    }),
                    ExtensionPlaceholder.configure({
                        placeholder,
                    }),
                    RichContentNodeMention,
                    MentionsExtension,
                ]}
                onUpdate={(content) => setComposedComment(content)}
                onCreate={(editor) => setEditor(createEditor(editor))}
                className="bg-bg-light border rounded mt-2 outline-none px-1 min-h-12"
                disabled={commentsLoading}
                onPressCmdEnter={sendComposedContent}
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
                    data-attr="discussions-comment"
                >
                    Add {replyingCommentId ? 'reply' : 'comment'}
                </LemonButton>
            </div>
        </div>
    )
}
