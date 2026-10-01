import { IconCheckCircle, IconWarning } from '@posthog/icons'
import { Spinner } from '@posthog/quill'

import type { CanvasSaveStatus } from '../../editing/canvasEditLogic'

/** Whether the author's edits are published yet. */
export function CanvasBlocksSaveIndicator({ status }: { status: CanvasSaveStatus }): JSX.Element {
    if (status.error) {
        return (
            <span
                className="flex items-center gap-1 text-xs text-destructive-foreground"
                data-attr="canvas-save-status"
            >
                <IconWarning />
                Not saved
            </span>
        )
    }
    if (status.saving || status.dirty) {
        return (
            <span className="flex items-center gap-1 text-xs text-muted-foreground" data-attr="canvas-save-status">
                <Spinner className="size-3" aria-hidden="true" />
                Saving
            </span>
        )
    }
    return (
        <span className="flex items-center gap-1 text-xs text-muted-foreground" data-attr="canvas-save-status">
            <IconCheckCircle />
            Saved
        </span>
    )
}
