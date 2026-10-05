import { useActions, useValues } from 'kea'

import { IconCollapse45 } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { canvasFullscreenLogic } from './canvasFullscreenLogic'

export function CanvasFullscreenExit(): JSX.Element | null {
    const { fullscreen } = useValues(canvasFullscreenLogic)
    const { setFullscreen } = useActions(canvasFullscreenLogic)

    if (!fullscreen) {
        return null
    }
    return (
        <div className="absolute top-2 right-2 z-10">
            <Tooltip>
                <TooltipTrigger
                    delay={0}
                    render={
                        <Button
                            size="icon-sm"
                            variant="outline"
                            className="bg-background"
                            aria-label="Exit full page"
                            onClick={() => setFullscreen(false)}
                            data-attr="canvas-fullscreen-exit"
                        />
                    }
                >
                    <IconCollapse45 />
                </TooltipTrigger>
                <TooltipContent>Exit full page (Esc)</TooltipContent>
            </Tooltip>
        </div>
    )
}
