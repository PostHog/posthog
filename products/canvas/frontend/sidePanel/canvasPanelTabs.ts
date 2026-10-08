import { SidePanelTab } from '~/types'

// pinned: panel tab keys, sent as the `tab` property of the panel_tab_change action
export type CanvasPanelTab = 'chat' | 'blocks' | 'timeline'

/** The app side panel tab each canvas panel tab shows in. A new tab adds a row here and a case in CanvasSidePanelTabBody. */
export const CANVAS_PANEL_SIDE_PANEL_TABS: Record<CanvasPanelTab, SidePanelTab> = {
    chat: SidePanelTab.CanvasChat,
    blocks: SidePanelTab.CanvasBlocks,
    timeline: SidePanelTab.CanvasTimeline,
}

/** The canvas panel tab an app side panel tab shows, or null for a tab that is not a canvas one. */
export function canvasPanelTab(tab: SidePanelTab | null): CanvasPanelTab | null {
    return (
        (Object.keys(CANVAS_PANEL_SIDE_PANEL_TABS) as CanvasPanelTab[]).find(
            (key) => CANVAS_PANEL_SIDE_PANEL_TABS[key] === tab
        ) ?? null
    )
}
