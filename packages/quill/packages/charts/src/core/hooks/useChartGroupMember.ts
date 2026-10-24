import { useCallback, useContext, useLayoutEffect, useMemo, useRef, useSyncExternalStore } from 'react'

import {
    buildChartGroupXIndex,
    chartGroupRangeAt,
    chartGroupXAt,
    matchChartGroupRange,
    matchChartGroupX,
    type ChartGroupRange,
    type ChartGroupXIndex,
} from '../chart-group'
import { ChartGroupContext } from '../chart-group-context'
import type { ChartGroupHover, ChartGroupStore } from '../chart-group-store'
import type { ExternalHoverSource } from './useHoverAnimation'

const NO_SELECTION = (): null => null
const NO_INDEX = (): number => -1
const NOOP_SUBSCRIBE = (): (() => void) => () => {}
const NO_LABELS = buildChartGroupXIndex([])

interface UseChartGroupMemberOptions {
    /** False keeps the chart out of the enclosing group. */
    enabled: boolean
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
    /** Reports a drag over `startIndex..endIndex` to the group's `onZoom`. Null when the group has none,
     *  or when this chart's labels are not times, since a zoom range is a time range. */
    zoom: ((startIndex: number, endIndex: number) => void) | null
    /** Shares a brush over `startIndex..endIndex` with the group. Null when selection sync is off. */
    select: ((startIndex: number, endIndex: number) => void) | null
    /** The group selection mapped onto this chart's labels. */
    selection: { startIndex: number; endIndex: number } | null
}

function createMatcher(store: ChartGroupStore, id: number, xIndex: ChartGroupXIndex): () => number {
    let lastHover: ChartGroupHover | null = null
    let lastIndex = -1
    return () => {
        const hover = store.getHover()
        if (hover !== lastHover) {
            lastHover = hover
            lastIndex = hover && hover.sourceId !== id ? matchChartGroupX(xIndex, hover.x) : -1
        }
        return lastIndex
    }
}

/** Joins the enclosing `ChartGroup`: publishes this chart's hover, and maps the group's hover,
 *  zoom and selection onto this chart's labels. Inert outside a group or when `enabled` is false. */
export function useChartGroupMember({ enabled, labels }: UseChartGroupMemberOptions): ChartGroupMember {
    const context = useContext(ChartGroupContext)
    const group = enabled ? context : null
    const store = group?.store ?? null

    const memberRef = useRef<{ store: ChartGroupStore; id: number } | null>(null)
    if (store && memberRef.current?.store !== store) {
        memberRef.current = { store, id: store.nextMemberId() }
    }
    const id = store ? (memberRef.current?.id ?? -1) : -1

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
            const x = hoverIndex >= 0 ? chartGroupXAt(xIndex, hoverIndex) : null
            if (x) {
                store.setHover({ sourceId: id, x })
            } else {
                store.clearHover(id)
            }
        },
        [store, id, xIndex]
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

    return { hoverSource, tooltipSource, publish, zoom, select, selection }
}

/** The enclosing group's hover mapped onto `labels`, as React state that changes only when the
 *  matched index does. -1 outside a group, without labels, or when `enabled` is false. For DOM that
 *  follows the group hover, such as a stat tile's headline. */
export function useChartGroupHoverIndex(labels: string[] | undefined, enabled = true): number {
    const context = useContext(ChartGroupContext)
    const store = enabled && labels ? (context?.store ?? null) : null
    const getIndex = useMemo(
        () => (store && labels ? createMatcher(store, -1, buildChartGroupXIndex(labels)) : NO_INDEX),
        [store, labels]
    )
    return useSyncExternalStore(store?.subscribeHover ?? NOOP_SUBSCRIBE, getIndex, NO_INDEX)
}
