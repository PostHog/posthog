import { useActions, useValues } from 'kea'

import { IconSidePanel } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { canvasPanelTab } from '../sidePanel/canvasPanelTabs'
import { canvasSidePanelLogic } from '../sidePanel/canvasSidePanelLogic'
import { canvasSceneLogic } from './canvasSceneLogic'

/** Opens the canvas's chat, comments, and timeline in the app side panel. The panel closes from its own bar. */
export function CanvasSidePanelToggle(): JSX.Element | null {
    const { canvas, sidePanelAvailable } = useValues(canvasSceneLogic)
    const { selectedTab, sidePanelOpen } = useValues(canvasSidePanelLogic)
    const { openTab } = useActions(canvasSidePanelLogic)

    if (!canvas || !sidePanelAvailable || (sidePanelOpen && canvasPanelTab(selectedTab))) {
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
                        aria-label="Show side panel"
                        onClick={() => openTab(canvasPanelTab(selectedTab) ?? 'chat', canvas.id)}
                        data-attr="canvas-panel-toggle"
                    />
                }
            >
                <IconSidePanel />
            </TooltipTrigger>
            <TooltipContent>Show side panel</TooltipContent>
        </Tooltip>
    )
}
