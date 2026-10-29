import React, { createContext, useContext, useEffect, useId, useMemo, useState, useSyncExternalStore } from 'react'

interface HoverSyncStore {
    subscribe: (listener: () => void) => () => void
    publish: (sourceId: string, label: string | null) => void
    sourceId: string | null
    label: string | null
}

function createHoverSyncStore(): HoverSyncStore {
    const listeners = new Set<() => void>()
    const store: HoverSyncStore = {
        sourceId: null,
        label: null,
        subscribe: (listener) => {
            listeners.add(listener)
            return () => listeners.delete(listener)
        },
        publish: (sourceId, label) => {
            // A chart clearing its hover must not wipe another chart's newer hover.
            if (label == null && store.sourceId !== sourceId) {
                return
            }
            if (store.sourceId === sourceId && store.label === label) {
                return
            }
            store.sourceId = label == null ? null : sourceId
            store.label = label
            listeners.forEach((listener) => listener())
        },
    }
    return store
}

const HoverSyncContext = createContext<HoverSyncStore | null>(null)

/** Shares the hovered x position between the charts inside it, like a dashboard's shared crosshair.
 *  Hovering one chart draws a crosshair at the same x on the others: the same label, or for date
 *  labels the nearest point in time. Only the hovered chart shows its tooltip. Charts in different
 *  providers do not sync, so wrap each group that should move together. */
export function ChartHoverSync({ children }: { children: React.ReactNode }): React.ReactElement {
    const [store] = useState(createHoverSyncStore)
    return <HoverSyncContext.Provider value={store}>{children}</HoverSyncContext.Provider>
}

/** Publishes this chart's hovered label to the enclosing {@link ChartHoverSync} and returns the
 *  index in `labels` another chart is hovering, or -1. Without a provider, or with `enabled` off for
 *  a chart whose labels are not x values, it does nothing. */
export function useHoverSync(labels: string[], hoveredLabel: string | null, enabled = true): number {
    const provided = useContext(HoverSyncContext)
    const store = enabled ? provided : null
    const id = useId()

    useEffect(() => {
        store?.publish(id, hoveredLabel)
    }, [store, id, hoveredLabel])
    useEffect(() => () => store?.publish(id, null), [store, id])

    // Only charts inside a provider pay for the lookup.
    const findIndex = useMemo(() => (store ? buildSyncedIndexFinder(labels) : null), [store, labels])
    return useSyncExternalStore(
        store?.subscribe ?? noopSubscribe,
        () => (!findIndex || store?.label == null || store.sourceId === id ? -1 : findIndex(store.label)),
        () => -1
    )
}

function noopSubscribe(): () => void {
    return () => {}
}

/** Epoch ms of an ISO date label (`2026-03-01`, `2026-03-01T10:00:00Z`), else NaN. Other strings
 *  such as `'2'` are categories, even where `Date.parse` would read them as a year. */
function parseDateLabel(label: string): number {
    return /^\d{4}-\d{2}-\d{2}/.test(label) ? Date.parse(label) : NaN
}

/** Resolves a label from another chart to an index here: an exact label match, else the nearest
 *  date when both sides are ISO dates and the date falls inside this chart's range. */
export function buildSyncedIndexFinder(labels: readonly string[]): (label: string) => number {
    const exact = new Map(labels.map((label, i) => [label, i]))
    const times = labels.map(parseDateLabel)
    const sortedByTime = times.every(isFinite) && times.every((t, i) => i === 0 || t >= times[i - 1])
    return (label) => {
        const match = exact.get(label)
        if (match != null) {
            return match
        }
        const t = parseDateLabel(label)
        if (!sortedByTime || !isFinite(t) || times.length === 0 || t < times[0] || t > times[times.length - 1]) {
            return -1
        }
        let lo = 0
        let hi = times.length - 1
        while (hi - lo > 1) {
            const mid = (lo + hi) >> 1
            if (times[mid] <= t) {
                lo = mid
            } else {
                hi = mid
            }
        }
        return t - times[lo] <= times[hi] - t ? lo : hi
    }
}
