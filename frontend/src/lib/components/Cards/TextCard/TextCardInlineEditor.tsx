import { EditorContent } from '@tiptap/react'
import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import 'lib/components/MarkdownEditor/shared/RichMarkdownEditor.scss'
import { getTiptapEditorDom } from 'lib/components/MarkdownEditor/shared/tiptapEditorDom'
import { useRichContentEditor } from 'lib/components/RichContentEditor'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { DashboardTile, DashboardType, QueryBasedInsightModel } from '~/types'

import { markdownToTextCardDoc, textCardDocToMarkdown, TEXT_CARD_MARKDOWN_EXTENSIONS } from './textCardMarkdown'
import { textCardModalLogic } from './textCardModalLogic'

export interface TextCardInlineEditorProps {
    dashboard: DashboardType<QueryBasedInsightModel>
    tile: DashboardTile<QueryBasedInsightModel>
    onClose: () => void
}

export function TextCardInlineEditor({ dashboard, tile, onClose }: TextCardInlineEditorProps): JSX.Element {
    const logic = textCardModalLogic({ dashboard, textTileId: tile.id, onClose })
    const { isTextTileSubmitting, textTileValidationErrors } = useValues(logic)
    const { setTextTileValue, submitTextTile, resetTextTile } = useActions(logic)

    const initialDoc = useMemo(() => markdownToTextCardDoc(tile.text?.body), [tile.text?.body])

    const editor = useRichContentEditor({
        extensions: TEXT_CARD_MARKDOWN_EXTENSIONS,
        initialContent: initialDoc,
        onUpdate: (content) => setTextTileValue('body', textCardDocToMarkdown(content)),
    })

    useEffect(() => {
        if (!editor || !getTiptapEditorDom(editor)) {
            return
        }
        // Defer past TipTap init; synchronous focus() can throw "Applying a mismatched transaction" in Safari.
        const id = window.setTimeout(() => {
            if (!editor.isDestroyed) {
                editor.commands.focus('end')
            }
        }, 0)
        return () => window.clearTimeout(id)
    }, [editor, editor?.isInitialized])

    const cancel = (): void => {
        if (isTextTileSubmitting) {
            return
        }
        resetTextTile()
        onClose()
    }

    return (
        <div
            className="flex min-h-0 w-full flex-1 flex-col"
            // Keep grid drag/resize gestures and dashboard hotkeys away from the editor
            onMouseDown={(e) => e.stopPropagation()}
            onKeyDown={(e) => {
                if (e.key === 'Escape') {
                    e.stopPropagation()
                    cancel()
                } else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                    e.preventDefault()
                    e.stopPropagation()
                    submitTextTile()
                }
            }}
        >
            <div className="RichMarkdownEditor min-h-0 flex-1 overflow-auto">
                <EditorContent
                    editor={editor}
                    className="RichMarkdownEditor__content h-full p-4 pr-14"
                    data-attr="text-card-inline-edit-area"
                />
            </div>
            <div className="flex shrink-0 items-center justify-end gap-2 border-t border-primary p-2">
                <LemonButton
                    size="small"
                    type="secondary"
                    onClick={cancel}
                    disabledReason={isTextTileSubmitting ? 'Saving in progress' : null}
                    data-attr="cancel-text-tile-inline-edit"
                >
                    Cancel
                </LemonButton>
                <LemonButton
                    size="small"
                    type="primary"
                    onClick={submitTextTile}
                    loading={isTextTileSubmitting}
                    disabledReason={textTileValidationErrors.body as string | null}
                    data-attr="save-text-tile-inline-edit"
                >
                    Save
                </LemonButton>
            </div>
        </div>
    )
}
