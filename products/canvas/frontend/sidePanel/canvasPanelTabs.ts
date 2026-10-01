// pinned: panel tab keys, sent as the `tab` property of the panel_tab_change action
export type CanvasPanelTab = 'chat' | 'comments' | 'timeline'

export interface CanvasPanelTabDefinition {
    key: CanvasPanelTab
    label: string
}

/** The side panel's tabs, in the order they show. A new tab adds a row here and a case in CanvasSidePanelTabBody. */
export const CANVAS_PANEL_TABS: readonly CanvasPanelTabDefinition[] = [
    { key: 'chat', label: 'Chat' },
    { key: 'comments', label: 'Comments' },
    { key: 'timeline', label: 'Timeline' },
]
