import { useCallback, useContext, useId, useLayoutEffect, useMemo, useSyncExternalStore } from 'react'

import {
    buildChartGroupXIndex,
    chartGroupEndAt,
    chartGroupRangeAt,
    matchChartGroupRange,
    matchChartGroupX,
    type ChartGroupRange,
    type ChartGroupXIndex,
} from '../chart-group'
import { ChartGroupContext } from '../chart-group-context'
import type { ChartGroupStore } from '../chart-group-store'
import type { ExternalHoverSource } from './useHoverAnimation'

const NO_SELECTION = (): null => null
const NO_INDEX = (): number => -1
const NOOP_SUBSCRIBE = (): (() => void) => () => {}
const NO_LABELS = buildChartGroupXIndex([])

interface UseChartGroupMemberOptions {
    /** The x values this chart lines up on. */
    labels: string[]
}

export interface ChartGroupMember {
    /** The group hover mapped onto this chart, for the hover canvas. Null outside a group. */
    hoverSource: ExternalHoverSource | null
    /** The group hover mapped onto this chart, set only while the group shows every chart's tooltip. */
    tooltipSource: ExternalHoverSource | null
    /** Shares this chart's hover index with the group; -1 clears it. Call from a layout effect, so the
     *  other charts schedule their repaint in the same frame as this one. */
    publish: (hoverIndex: number) => void
    /** Publishes `hoverIndex` again when the group hover belongs to another chart. A pinned chart calls
     *  it as the pointer comes back, since its hover index does not change then. */
    reclaim: (hoverIndex: number) => void
    /** Reports a drag over `startIndex..endIndex` to the group's `onZoom`. Null when the group has none,
     *  or when this chart's labels are not times, since a zoom range is a time range. */
    zoom: ((startIndex: number, endIndex: number) => void) | null
    /** Shares a brush over `startIndex..endIndex` with the group. Null when selection sync is off. */
    select: ((startIndex: number, endIndex: number) => void) | null
    /** The group selection mapped onto this chart's labels. */
    selection: { startIndex: number; endIndex: number } | null
}

function createMatcher(store: ChartGroupStore, id: string, xIndex: ChartGroupXIndex): () => number {
    let lastVersion = -1
    let lastIndex = -1
    return () => {
        const hover = store.getHover()
        const version = hover?.version ?? -1
        if (version !== lastVersion) {
            lastVersion = version
            lastIndex = hover && hover.sourceId !== id ? matchChartGroupX(xIndex, hover) : -1
        }
        return lastIndex
    }
}

/** Joins the enclosing `ChartGroup`: publishes this chart's hover, and maps the group's hover,
 *  zoom and selection onto this chart's labels. Inert outside a group. */
export function useChartGroupMember({ labels }: UseChartGroupMemberOptions): ChartGroupMember {
    const group = useContext(ChartGroupContext)
    const store = group?.store ?? null
    const id = useId()

    // Charts outside a group skip the per-label parse.
    const xIndex = useMemo(() => (store ? buildChartGroupXIndex(labels) : NO_LABELS), [store, labels])

    const getIndex = useMemo(() => (store ? createMatcher(store, id, xIndex) : NO_INDEX), [store, id, xIndex])
    const syncCrosshair = group?.syncCrosshair ?? false
    const hoverSource = useMemo<ExternalHoverSource | null>(
        () => (store && syncCrosshair ? { subscribe: store.subscribeHover, getIndex } : null),
        [store, syncCrosshair, getIndex]
    )

    const tooltipAll = group?.syncTooltip === 'all'
    const tooltipSource = useMemo<ExternalHoverSource | null>(
        () => (store && tooltipAll ? { subscribe: store.subscribeHover, getIndex } : null),
        [store, tooltipAll, getIndex]
    )

    const publish = useCallback(
        (hoverIndex: number): void => {
            if (!store) {
                return
            }
            const label = hoverIndex >= 0 ? xIndex.labels[hoverIndex] : undefined
            if (label == null) {
                store.clearHover(id)
                return
            }
            store.setHover(id, label, xIndex.times?.[hoverIndex] ?? null, chartGroupEndAt(xIndex, hoverIndex))
        },
        [store, id, xIndex]
    )

    const reclaim = useCallback(
        (hoverIndex: number): void => {
            if (store && hoverIndex >= 0 && store.getHover()?.sourceId !== id) {
                publish(hoverIndex)
            }
        },
        [store, id, publish]
    )

    useLayoutEffect(() => {
        if (!store) {
            return
        }
        return () => store.clearHover(id)
    }, [store, id])

    const groupZoom = xIndex.times ? (group?.zoom ?? null) : null
    const zoom = useMemo(
        () =>
            groupZoom
                ? (startIndex: number, endIndex: number): void =>
                      groupZoom(chartGroupRangeAt(xIndex, startIndex, endIndex))
                : null,
        [groupZoom, xIndex]
    )

    const groupSelect = group?.syncSelection ? group.select : null
    const select = useMemo(
        () =>
            groupSelect
                ? (startIndex: number, endIndex: number): void =>
                      groupSelect(chartGroupRangeAt(xIndex, startIndex, endIndex))
                : null,
        [groupSelect, xIndex]
    )

    const groupSelection = useSyncExternalStore<ChartGroupRange | null>(
        group?.syncSelection && store ? store.subscribeSelection : NOOP_SUBSCRIBE,
        group?.syncSelection && store ? store.getSelection : NO_SELECTION,
        NO_SELECTION
    )
    const selection = useMemo(
        () => (groupSelection ? matchChartGroupRange(xIndex, groupSelection) : null),
        [groupSelection, xIndex]
    )

    return { hoverSource, tooltipSource, publish, reclaim, zoom, select, selection }
}

/** The enclosing `ChartGroup`'s hover mapped onto `labels`, as React state that changes only when the
 *  matched index does. -1 outside a group or without labels. Use it for DOM that follows the group
 *  hover, such as a stat tile's headline. */
export function useChartGroupHoverIndex(labels: string[] | undefined): number {
    const context = useContext(ChartGroupContext)
    const store = labels ? (context?.store ?? null) : null
    const getIndex = useMemo(
        () => (store && labels ? createMatcher(store, '', buildChartGroupXIndex(labels)) : NO_INDEX),
        [store, labels]
    )
    return useSyncExternalStore(store?.subscribeHover ?? NOOP_SUBSCRIBE, getIndex, NO_INDEX)
}
