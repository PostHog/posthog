import { useActions, useValues } from 'kea'
import { ChangeEvent, KeyboardEvent, useState } from 'react'

import { Button, Input, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { canvasSceneLogic } from './canvasSceneLogic'

/** The canvas's name in the toolbar. Select it to rename the canvas. */
export function CanvasNameField(): JSX.Element | null {
    const { canvas } = useValues(canvasSceneLogic)
    const { renameCanvas } = useActions(canvasSceneLogic)
    const [draft, setDraft] = useState<string | null>(null)

    if (!canvas) {
        return null
    }
    if (draft !== null) {
        const save = (): void => {
            renameCanvas(draft)
            setDraft(null)
        }
        return (
            <Input
                autoFocus
                value={draft}
                aria-label="Canvas name"
                className="w-64 max-w-full min-w-0"
                onChange={(event: ChangeEvent<HTMLInputElement>) => setDraft(event.target.value)}
                onBlur={save}
                onKeyDown={(event: KeyboardEvent<HTMLInputElement>) => {
                    if (event.key === 'Enter') {
                        save()
                    } else if (event.key === 'Escape') {
                        setDraft(null)
                    }
                }}
                data-attr="canvas-name-input"
            />
        )
    }
    return (
        <Tooltip>
            <TooltipTrigger
                delay={400}
                render={
                    <Button
                        size="sm"
                        variant="default"
                        className="min-w-0 justify-start font-medium"
                        onClick={() => setDraft(canvas.name)}
                        data-attr="canvas-name"
                    />
                }
            >
                <span className="truncate">{canvas.name}</span>
            </TooltipTrigger>
            <TooltipContent>Rename canvas</TooltipContent>
        </Tooltip>
    )
}
