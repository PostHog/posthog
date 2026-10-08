import { useActions, useValues } from 'kea'
import { ChangeEvent, KeyboardEvent, useEffect } from 'react'

import { IconComment } from '@posthog/icons'
import { Button, Textarea } from '@posthog/quill'

import { canvasCommentsLogic } from './canvasCommentsLogic'

const FORM_WIDTH_PX = 288
// About the width of the collapsed Comment button, so it never runs off the right edge.
const BUTTON_WIDTH_PX = 120
const VIEWPORT_MARGIN_PX = 8

/**
 * The floating "Comment" action by text the viewer selected in the canvas. It opens into a
 * small form, and saving it starts a thread anchored to that text.
 */
export function CanvasSelectionCommentAction(): JSX.Element | null {
    const { textSelection, selectionDraft, writing, commentsEnabled, composing } = useValues(canvasCommentsLogic)
    const { createComment, dismissTextSelection, setSelectionDraft, openSelectionComposer } =
        useActions(canvasCommentsLogic)
    const saving = writing === 'selection'

    useEffect(() => {
        if (!textSelection) {
            return
        }
        const onKeyDown = (event: globalThis.KeyboardEvent): void => {
            if (event.key === 'Escape') {
                dismissTextSelection()
            }
        }
        window.addEventListener('keydown', onKeyDown)
        return () => window.removeEventListener('keydown', onKeyDown)
    }, [textSelection, dismissTextSelection])

    if (!textSelection || !commentsEnabled) {
        return null
    }
    // The selection reports page coordinates of its last line, so the action sits just under it.
    const width = composing ? FORM_WIDTH_PX : BUTTON_WIDTH_PX
    const left = Math.max(
        VIEWPORT_MARGIN_PX,
        Math.min(textSelection.rect.left, window.innerWidth - width - VIEWPORT_MARGIN_PX)
    )
    const top = Math.max(
        VIEWPORT_MARGIN_PX,
        Math.min(textSelection.rect.bottom + 6, window.innerHeight - (composing ? 300 : 48))
    )

    return (
        <div
            data-quill
            className="fixed z-50 flex flex-col gap-2"
            // Dynamic coordinates from the frame's selection rect cannot be expressed as utility classes.
            style={{ top, left, width: composing ? FORM_WIDTH_PX : undefined }}
            data-attr="canvas-selection-comment"
        >
            {!composing ? (
                <Button
                    size="sm"
                    variant="outline"
                    className="self-start bg-background shadow-md"
                    onClick={openSelectionComposer}
                    data-attr="canvas-selection-comment-open"
                >
                    <IconComment />
                    Comment…
                </Button>
            ) : (
                <form
                    className="flex max-h-[calc(100vh-16px)] flex-col gap-2 overflow-y-auto rounded-md border border-border bg-background p-2 shadow-md"
                    onSubmit={(event) => {
                        event.preventDefault()
                        if (selectionDraft.trim() && !saving) {
                            createComment()
                        }
                    }}
                >
                    <div className="text-xs text-muted-foreground">This quote will be shared with your comment:</div>
                    <blockquote className="m-0 max-h-24 shrink-0 overflow-y-auto whitespace-pre-wrap break-words border-l-2 border-border pl-2 text-xs">
                        {textSelection.quote}
                    </blockquote>
                    <Textarea
                        autoFocus
                        aria-label="Comment on the selected text"
                        placeholder="Add a comment about this selection"
                        rows={3}
                        value={selectionDraft}
                        disabled={saving}
                        onChange={(event: ChangeEvent<HTMLTextAreaElement>) => setSelectionDraft(event.target.value)}
                        onKeyDown={(event: KeyboardEvent<HTMLTextAreaElement>) => {
                            if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
                                event.preventDefault()
                                event.currentTarget.form?.requestSubmit()
                            }
                        }}
                        data-attr="canvas-selection-comment-input"
                    />
                    <div className="flex justify-end gap-2">
                        <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            disabled={saving}
                            onClick={() => dismissTextSelection()}
                        >
                            Cancel
                        </Button>
                        <Button
                            type="submit"
                            size="sm"
                            variant="primary"
                            loading={saving}
                            disabled={!selectionDraft.trim()}
                            data-attr="canvas-selection-comment-submit"
                        >
                            Comment
                        </Button>
                    </div>
                </form>
            )}
        </div>
    )
}
