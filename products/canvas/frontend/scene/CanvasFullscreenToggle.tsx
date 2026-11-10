import { useActions, useValues } from 'kea'

import { IconExpand45 } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { canvasEditLogic } from '../editing/canvasEditLogic'
import { canvasHistoryLogic } from '../history/canvasHistoryLogic'
import { canvasFullscreenLogic } from './canvasFullscreenLogic'
import { canvasSceneLogic } from './canvasSceneLogic'

export function CanvasFullscreenToggle(): JSX.Element | null {
    const { bodyState } = useValues(canvasSceneLogic)
    const { editing } = useValues(canvasEditLogic)
    const { browseVersionId } = useValues(canvasHistoryLogic)
    const { setFullscreen } = useActions(canvasFullscreenLogic)

    if ((bodyState !== 'built' && bodyState !== 'draft') || editing || browseVersionId) {
        return null
    }
    return (
        <Tooltip>
            <TooltipTrigger
                delay={0}
                render={
                    <Button
                        size="icon-sm"
                        variant="default"
                        aria-label="Open full page"
                        onClick={() => setFullscreen(true)}
                        data-attr="canvas-fullscreen-enter"
                    />
                }
            >
                <IconExpand45 />
            </TooltipTrigger>
            <TooltipContent>Open full page</TooltipContent>
        </Tooltip>
    )
}
