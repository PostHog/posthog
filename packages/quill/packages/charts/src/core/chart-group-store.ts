import type { ChartGroupRange, ChartGroupX } from './chart-group'

export interface ChartGroupHover extends ChartGroupX {
    /** Member id of the chart under the pointer. */
    sourceId: string
    /** Increases on every change. The store reuses one hover object, so readers compare this. */
    version: number
}

/** Hover and selection shared by the charts of one `ChartGroup`. Lives outside React so a hover
 *  repaints each member's hover canvas without re-rendering any chart. */
export interface ChartGroupStore {
    /** The current hover, or null. The same object is mutated in place on each change. */
    getHover: () => Readonly<ChartGroupHover> | null
    setHover: (sourceId: string, label: string, time: number | null, end: number | null) => void
    /** Clears the hover, but only when `sourceId` still owns it. A chart's late mouseleave must
     *  not wipe the hover the next chart has already published. */
    clearHover: (sourceId: string) => void
    subscribeHover: (listener: () => void) => () => void
    getSelection: () => ChartGroupRange | null
    setSelection: (selection: ChartGroupRange | null) => void
    subscribeSelection: (listener: () => void) => () => void
}

function sameRange(a: ChartGroupRange | null, b: ChartGroupRange | null): boolean {
    if (a === b) {
        return true
    }
    if (!a || !b) {
        return false
    }
    return a.startLabel === b.startLabel && a.endLabel === b.endLabel && a.from === b.from && a.to === b.to
}

function emit(listeners: Set<() => void>): void {
    for (const listener of listeners) {
        listener()
    }
}

export function createChartGroupStore(initialSelection: ChartGroupRange | null = null): ChartGroupStore {
    // Hover changes on every hovered label, so it mutates one object instead of allocating per change.
    const hoverState: ChartGroupHover = { sourceId: '', label: '', time: null, end: null, version: 0 }
    let hovering = false
    let selection: ChartGroupRange | null = initialSelection
    const hoverListeners = new Set<() => void>()
    const selectionListeners = new Set<() => void>()

    return {
        getHover: () => (hovering ? hoverState : null),
        setHover: (sourceId, label, time, end) => {
            if (hovering && hoverState.sourceId === sourceId && hoverState.label === label) {
                return
            }
            hovering = true
            hoverState.sourceId = sourceId
            hoverState.label = label
            hoverState.time = time
            hoverState.end = end
            hoverState.version++
            emit(hoverListeners)
        },
        clearHover: (sourceId) => {
            if (!hovering || hoverState.sourceId !== sourceId) {
                return
            }
            hovering = false
            hoverState.version++
            emit(hoverListeners)
        },
        subscribeHover: (listener) => {
            hoverListeners.add(listener)
            return () => hoverListeners.delete(listener)
        },
        getSelection: () => selection,
        setSelection: (next) => {
            // A parent may rebuild an equal range on every render, which must not re-render every member.
            if (sameRange(next, selection)) {
                return
            }
            selection = next
            emit(selectionListeners)
        },
        subscribeSelection: (listener) => {
            selectionListeners.add(listener)
            return () => selectionListeners.delete(listener)
        },
    }
}
