import { useActions, useValues } from 'kea'

import { IconSidebarClose, IconSidebarOpen } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { canvasSidePanelLogic } from '../sidePanel/canvasSidePanelLogic'
import { canvasSceneLogic } from './canvasSceneLogic'

/** Shows or hides the chat, comments, and timeline panel. */
export function CanvasSidePanelToggle(): JSX.Element | null {
    const { canvas, sidePanelAvailable, sidePanelOpen } = useValues(canvasSceneLogic)
    const { setCollapsed } = useActions(canvasSidePanelLogic)

    if (!canvas || !sidePanelAvailable) {
        return null
    }
    const label = sidePanelOpen ? 'Hide panel' : 'Show chat, comments, and timeline'
    return (
        <Tooltip>
            <TooltipTrigger
                delay={0}
                render={
                    <Button
                        size="icon-sm"
                        variant="default"
                        aria-label={label}
                        aria-pressed={sidePanelOpen}
                        onClick={() => setCollapsed(sidePanelOpen, canvas.id)}
                        data-attr="canvas-panel-toggle"
                    />
                }
            >
                {sidePanelOpen ? <IconSidebarOpen /> : <IconSidebarClose />}
            </TooltipTrigger>
            <TooltipContent>{label}</TooltipContent>
        </Tooltip>
    )
}
