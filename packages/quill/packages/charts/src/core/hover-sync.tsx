import React, { createContext, useContext, useEffect, useId, useMemo, useState, useSyncExternalStore } from 'react'

interface HoverSyncStore {
    subscribe: (listener: () => void) => () => void
    publish: (sourceId: string, label: string | null) => void
    sourceId: string | null
    label: string | null
}

function createHoverSyncStore(): HoverSyncStore {
    const listeners = new Set<() => void>()
    // Every chart that holds a label, newest last. A pinned tooltip keeps its chart's label, so when
    // a newer hover ends the crosshair returns to the pinned chart.
    const active = new Map<string, string>()
    const store: HoverSyncStore = {
        sourceId: null,
        label: null,
        subscribe: (listener) => {
            listeners.add(listener)
            return () => listeners.delete(listener)
        },
        publish: (sourceId, label) => {
            active.delete(sourceId)
            if (label != null) {
                active.set(sourceId, label)
            }
            const [newestId = null, newestLabel = null] = Array.from(active).at(-1) ?? []
            if (store.sourceId === newestId && store.label === newestLabel) {
                return
            }
            store.sourceId = newestId
            store.label = newestLabel
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

const HAS_OFFSET = /([Zz]|[+-]\d{2}:?\d{2})$/

/** Epoch ms of an ISO date label (`2026-03-01`, `2026-03-01 10:00:00`, `2026-03-01T10:00:00Z`),
 *  else NaN. A label without an offset reads as UTC, so date-only and date-time labels share one
 *  clock whatever the browser's timezone. Other strings such as `'2'` are categories, even where
 *  `Date.parse` would read them as a year. */
function parseDateLabel(label: string): number {
    if (!/^\d{4}-\d{2}-\d{2}/.test(label)) {
        return NaN
    }
    if (HAS_OFFSET.test(label)) {
        return Date.parse(label)
    }
    const iso = label.replace(' ', 'T')
    return Date.parse(iso.length === 10 ? `${iso}T00:00:00Z` : `${iso}Z`)
}

/** Resolves a label from another chart to an index here: an exact label match, else, when both
 *  sides are ISO dates, the bucket that contains the date. Labels are bucket starts, and the last
 *  bucket is as wide as the step before it. */
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
        if (!sortedByTime || !isFinite(t) || times.length === 0 || t < times[0]) {
            return -1
        }
        const last = times.length - 1
        if (t >= times[last]) {
            const lastStep = last > 0 ? times[last] - times[last - 1] : 0
            return t === times[last] || t < times[last] + lastStep ? last : -1
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
        return lo
    }
}
