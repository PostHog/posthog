import { BindLogic, useValues } from 'kea'

import { sidePanelContextLogic } from '~/layout/navigation-3000/sidepanel/sidePanelContextLogic'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'

import { canvasHistoryLogic } from '../history/canvasHistoryLogic'
import { canvasSceneLogic } from '../scene/canvasSceneLogic'
import { canvasPanelTab } from './canvasPanelTabs'
import { CanvasSidePanelTabBody } from './CanvasSidePanelTabBody'

/** The canvas's tabs in the app side panel: the agent chat, blocks, and version timeline. */
export function CanvasSidePanel(): JSX.Element | null {
    const { selectedTab } = useValues(sidePanelStateLogic)
    const { sceneSidePanelContext } = useValues(sidePanelContextLogic)
    const canvasId = sceneSidePanelContext.canvas_id
    const tab = canvasPanelTab(selectedTab)

    if (!canvasId || !tab) {
        return null
    }
    return (
        <BindLogic logic={canvasSceneLogic} props={{ id: canvasId }}>
            <BindLogic logic={canvasHistoryLogic} props={{ id: canvasId }}>
                <div
                    data-quill
                    className="flex h-full min-h-0 flex-col bg-background"
                    data-attr={`canvas-side-panel-${tab}`}
                >
                    <CanvasSidePanelTabBody tab={tab} canvasId={canvasId} />
                </div>
            </BindLogic>
        </BindLogic>
    )
}
