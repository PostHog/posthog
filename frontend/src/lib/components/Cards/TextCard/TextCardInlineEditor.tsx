import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { DashboardTile, DashboardType, QueryBasedInsightModel } from '~/types'

import { TextCardMarkdownEditor } from './TextCardMarkdownEditor'
import { textCardModalLogic } from './textCardModalLogic'

export interface TextCardInlineEditorProps {
    dashboard: DashboardType<QueryBasedInsightModel>
    tile: DashboardTile<QueryBasedInsightModel>
    onClose: () => void
}

export function TextCardInlineEditor({ dashboard, tile, onClose }: TextCardInlineEditorProps): JSX.Element {
    const logic = textCardModalLogic({ dashboard, textTileId: tile.id, onClose })
    const { textTile, isTextTileSubmitting, textTileValidationErrors } = useValues(logic)
    const { setTextTileValue, submitTextTile, resetTextTile } = useActions(logic)

    const cancel = (): void => {
        if (isTextTileSubmitting) {
            return
        }
        resetTextTile()
        onClose()
    }

    return (
        <div
            className="flex min-h-0 w-full flex-1 flex-col gap-2 p-2"
            // Keep grid drag/resize gestures away from the editor
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
            <div className="min-h-0 flex-1 overflow-auto">
                <TextCardMarkdownEditor
                    value={textTile.body}
                    onChange={(value) => setTextTileValue('body', value)}
                    minRows={6}
                    maxRows={20}
                />
            </div>
            <div className="flex shrink-0 items-center justify-end gap-2">
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
