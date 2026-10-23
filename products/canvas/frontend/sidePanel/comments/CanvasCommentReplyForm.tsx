import { useActions, useValues } from 'kea'
import { ChangeEvent, KeyboardEvent } from 'react'

import { Button, Textarea } from '@posthog/quill'

import { canvasCommentsLogic } from './canvasCommentsLogic'

/** Adds a reply to one thread. Cmd+Enter or Ctrl+Enter sends. */
export function CanvasCommentReplyForm({ rootId }: { rootId: string }): JSX.Element {
    const { writing, replyDrafts } = useValues(canvasCommentsLogic)
    const { replyToThread, setReplyDraft } = useActions(canvasCommentsLogic)
    const reply = replyDrafts[rootId] ?? ''
    const sending = writing === rootId
    const submit = (): void => {
        if (reply.trim() && !writing) {
            replyToThread(rootId)
        }
    }

    return (
        <form
            className="flex flex-col gap-1.5"
            onSubmit={(event) => {
                event.preventDefault()
                submit()
            }}
        >
            <Textarea
                aria-label="Reply"
                placeholder="Reply"
                rows={2}
                value={reply}
                disabled={sending}
                onChange={(event: ChangeEvent<HTMLTextAreaElement>) => setReplyDraft(rootId, event.target.value)}
                onKeyDown={(event: KeyboardEvent<HTMLTextAreaElement>) => {
                    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
                        event.preventDefault()
                        submit()
                    }
                }}
                data-attr="canvas-comment-reply-input"
            />
            {reply.trim() && (
                <div className="flex justify-end">
                    <Button
                        type="submit"
                        size="sm"
                        variant="primary"
                        loading={sending}
                        disabled={!!writing && !sending}
                        data-attr="canvas-comment-reply-submit"
                    >
                        Reply
                    </Button>
                </div>
            )}
        </form>
    )
}
