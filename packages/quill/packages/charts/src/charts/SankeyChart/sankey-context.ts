import { createContext, useContext } from 'react'

import type { SankeyChartLayout } from './sankey-data'

/** Layout-stable values exposed to Sankey overlays (node labels, column headers, custom
 *  decorations). Identity does not change on hover. */
export interface SankeyLayoutContextValue<NodeMeta = unknown, LinkMeta = NodeMeta> {
    layout: SankeyChartLayout<NodeMeta, LinkMeta>
    /** Returns the current canvas bounding rect, or null if the canvas is unmounted. */
    canvasBounds: () => DOMRect | null
}

export const SankeyLayoutContext = createContext<SankeyLayoutContextValue | null>(null)

/** Subscribes to the Sankey layout. Throws if used outside a `<SankeyChart>`. */
export function useSankeyLayout<NodeMeta = unknown, LinkMeta = NodeMeta>(): SankeyLayoutContextValue<
    NodeMeta,
    LinkMeta
> {
    const ctx = useContext(SankeyLayoutContext)
    if (!ctx) {
        throw new Error('useSankeyLayout must be used inside <SankeyChart>')
    }
    return ctx as SankeyLayoutContextValue<NodeMeta, LinkMeta>
}
