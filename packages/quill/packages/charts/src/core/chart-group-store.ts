import type { ChartGroupRange, ChartGroupX } from './chart-group'

export interface ChartGroupHover {
    /** Member id of the chart under the pointer. */
    sourceId: number
    x: ChartGroupX
}

/** Hover and selection shared by the charts of one `ChartGroup`. Lives outside React so a hover
 *  repaints each member's hover canvas without re-rendering any chart. */
export interface ChartGroupStore {
    getHover: () => ChartGroupHover | null
    setHover: (hover: ChartGroupHover) => void
    /** Clears the hover, but only when `sourceId` still owns it. A chart's late mouseleave must
     *  not wipe the hover the next chart has already published. */
    clearHover: (sourceId: number) => void
    subscribeHover: (listener: () => void) => () => void
    getSelection: () => ChartGroupRange | null
    setSelection: (selection: ChartGroupRange | null) => void
    subscribeSelection: (listener: () => void) => () => void
    nextMemberId: () => number
}

export function createChartGroupStore(initialSelection: ChartGroupRange | null = null): ChartGroupStore {
    let hover: ChartGroupHover | null = null
    let selection: ChartGroupRange | null = initialSelection
    let memberCount = 0
    const hoverListeners = new Set<() => void>()
    const selectionListeners = new Set<() => void>()
    const emit = (listeners: Set<() => void>): void => listeners.forEach((listener) => listener())

    return {
        getHover: () => hover,
        setHover: (next) => {
            if (hover && hover.sourceId === next.sourceId && hover.x.label === next.x.label) {
                return
            }
            hover = next
            emit(hoverListeners)
        },
        clearHover: (sourceId) => {
            if (hover?.sourceId !== sourceId) {
                return
            }
            hover = null
            emit(hoverListeners)
        },
        subscribeHover: (listener) => {
            hoverListeners.add(listener)
            return () => hoverListeners.delete(listener)
        },
        getSelection: () => selection,
        setSelection: (next) => {
            if (next === selection) {
                return
            }
            selection = next
            emit(selectionListeners)
        },
        subscribeSelection: (listener) => {
            selectionListeners.add(listener)
            return () => selectionListeners.delete(listener)
        },
        nextMemberId: () => ++memberCount,
    }
}
