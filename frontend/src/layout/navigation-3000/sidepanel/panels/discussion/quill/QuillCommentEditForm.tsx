import { useActions, useValues } from 'kea'

import { Button } from '@posthog/quill'

import { commentsLogic } from 'lib/components/Comments/commentsLogic'

import { CommentType } from '~/types'

import { LazyQuillCommentEditor } from './LazyQuillCommentEditor'

export function QuillCommentEditForm({ comment }: { comment: CommentType }): JSX.Element {
    const { editingComment, isSavingEditedComment, editingCommentRichContentEditor, isEditingCommentEmpty } =
        useValues(commentsLogic)
    const {
        setEditingComment,
        persistEditedComment,
        setEditingCommentRichContentEditor,
        onEditingCommentRichContentEditorUpdate,
    } = useActions(commentsLogic)

    const cancel = (): void => {
        setEditingComment(null)
        setEditingCommentRichContentEditor(null)
    }

    return (
        <div className="flex flex-col gap-2 pt-1">
            <LazyQuillCommentEditor
                placeholder="Edit comment"
                autoFocus
                // Seeded from the edit in progress, so collapsing the thread mid-edit loses nothing.
                initialContent={editingComment?.rich_content ?? comment.rich_content}
                onCreate={setEditingCommentRichContentEditor}
                onUpdate={(isEmpty) => {
                    if (editingCommentRichContentEditor && editingComment) {
                        setEditingComment({
                            ...editingComment,
                            rich_content: editingCommentRichContentEditor.getJSON(),
                        })
                        onEditingCommentRichContentEditorUpdate(isEmpty)
                    }
                }}
                onPressCmdEnter={persistEditedComment}
                disabled={isSavingEditedComment}
            />
            <div className="flex flex-wrap items-center justify-end gap-2">
                <Button variant="outline" onClick={cancel} disabled={isSavingEditedComment}>
                    Cancel
                </Button>
                <Button
                    variant="primary"
                    onClick={persistEditedComment}
                    loading={isSavingEditedComment}
                    disabledReason={isEditingCommentEmpty ? 'Write a message first' : null}
                    data-attr="discussions-comment-save-edit"
                >
                    Save
                </Button>
            </div>
        </div>
    )
}
