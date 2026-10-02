import { CanvasBlocksTab } from './blocks/CanvasBlocksTab'
import type { CanvasPanelTab } from './canvasPanelTabs'
import { CanvasChatTab } from './chat/CanvasChatTab'
import { CanvasCommentsTab } from './comments/CanvasCommentsTab'
import { CanvasTimelineTab } from './timeline/CanvasTimelineTab'

/** The content of one side panel tab. */
export function CanvasSidePanelTabBody({ tab, canvasId }: { tab: CanvasPanelTab; canvasId: string }): JSX.Element {
    switch (tab) {
        case 'chat':
            return <CanvasChatTab canvasId={canvasId} />
        case 'blocks':
            return <CanvasBlocksTab canvasId={canvasId} />
        case 'comments':
            return <CanvasCommentsTab />
        case 'timeline':
            return <CanvasTimelineTab />
    }
}
