import { LemonButton, LemonTextArea, LemonWidget } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { notebookCommentLogic } from './notebookCommentLogic'

export const NotebookComments = (): JSX.Element | null => {
    const { comment, isEditingComment } = useValues(notebookCommentLogic)
    const { saveComment, setIsEditingComment, setLocalContent, cancelEditingComment } = useActions(notebookCommentLogic)

    if (!comment) {
        return null
    }

    const isNew = comment.id === null
    const isComposing = isNew || isEditingComment

    return (
        <LemonWidget title="New comment">
            <div className="px-1.5 space-y-1.5 pb-1.5">
                {isComposing ? (
                    <LemonTextArea
                        autoFocus
                        placeholder={'Start typing...'}
                        className="mt-2"
                        value={comment.content}
                        onChange={setLocalContent}
                    />
                ) : (
                    <LemonMarkdown>{comment.content}</LemonMarkdown>
                )}
                <div className="flex space-x-1.5">
                    {isEditingComment ? (
                        <LemonButton type="primary" onClick={() => setIsEditingComment(true)}>
                            Edit
                        </LemonButton>
                    ) : (
                        <>
                            <LemonButton type="primary" onClick={saveComment}>
                                {isEditingComment ? 'Update' : 'Comment'}
                            </LemonButton>
                            <LemonButton type="tertiary" onClick={cancelEditingComment}>
                                Cancel
                            </LemonButton>
                        </>
                    )}
                </div>
            </div>
        </LemonWidget>
    )
}
