import { createContext, useContext } from 'react'

import type { PieLayout } from './radial-layout'

/** Layout-stable values exposed to radial overlays (slice labels, custom decorations). Identity
 *  does NOT change on hover. */
export interface RadialLayoutContextValue<Meta = unknown> {
    layout: PieLayout<Meta>
    /** Returns the current canvas bounding rect, or null if the canvas is unmounted. */
    canvasBounds: () => DOMRect | null
}

export const RadialLayoutContext = createContext<RadialLayoutContextValue | null>(null)

/** Subscribes to radial layout state. Throws if used outside a `<RadialChart>` / `<PieChart>`. */
export function useRadialLayout<Meta = unknown>(): RadialLayoutContextValue<Meta> {
    const ctx = useContext(RadialLayoutContext)
    if (!ctx) {
        throw new Error('useRadialLayout must be used inside a radial chart component (e.g. <PieChart>)')
    }
    return ctx as RadialLayoutContextValue<Meta>
}
