import { useActions, useValues } from 'kea'

import { IconCheck, IconPencil } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { canvasEditLogic } from './canvasEditLogic'

/** Enters edit mode, where the canvas's blocks can be selected, moved and changed by hand, and leaves it. */
export function CanvasEditToggle(): JSX.Element {
    const { editing, editUnavailableReason, entry } = useValues(canvasEditLogic)
    const { setEditing, finishEditing } = useActions(canvasEditLogic)

    if (editing) {
        return (
            <Button
                size="sm"
                variant="primary"
                onClick={finishEditing}
                loading={entry?.saving}
                data-attr="canvas-edit-done"
            >
                <IconCheck />
                Done
            </Button>
        )
    }
    return (
        <Tooltip>
            <TooltipTrigger delay={0} render={<span className="inline-flex" />}>
                <Button
                    size="sm"
                    variant="outline"
                    disabled={!!editUnavailableReason}
                    onClick={() => setEditing(true)}
                    data-attr="canvas-edit-toggle"
                >
                    <IconPencil />
                    Edit
                </Button>
            </TooltipTrigger>
            <TooltipContent>{editUnavailableReason ?? 'Select, move, and change blocks by hand'}</TooltipContent>
        </Tooltip>
    )
}
