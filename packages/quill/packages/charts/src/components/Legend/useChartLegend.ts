import { useCallback, useMemo, useState, type ReactNode } from 'react'

import type { ChartLegendConfig, ChartTheme, Series } from '../../core/types'
import type { LegendItem, LegendItemClickModifiers } from './Legend'
import { legendItemsFromSeries } from './legendItemsFromSeries'

/** True when the primary pointer is coarse (a touch screen), read live at click time. Guarded like
 *  `prefersReducedMotion` because `matchMedia` is absent in jsdom test workers and other non-browser
 *  hosts, where a bare access would throw mid-render. Missing support reads as a fine pointer. */
function isCoarsePointer(): boolean {
    return (
        typeof window !== 'undefined' &&
        typeof window.matchMedia === 'function' &&
        window.matchMedia('(pointer: coarse)').matches
    )
}

/** Mark each `hiddenKeys` series as `visibility.excluded` so the chart drops it from rendering,
 *  scales, tooltips, and hit-testing — leaving the visible series to rescale into the freed space.
 *  Other `visibility` flags are preserved. Returns the input untouched when nothing is hidden. */
export function applyHiddenSeries<Meta>(series: Series<Meta>[], hiddenKeys: ReadonlySet<string>): Series<Meta>[] {
    if (hiddenKeys.size === 0) {
        return series
    }
    return series.map((s) => (hiddenKeys.has(s.key) ? { ...s, visibility: { ...s.visibility, excluded: true } } : s))
}

/** One legend row's visibility state plus the actions that can change it, handed to
 *  {@link ChartLegendConfig.renderItem} so a consumer's row menu doesn't re-derive any of it. The
 *  actions run the same paths as clicking (`isolate`) and ⌘/Ctrl-clicking (`toggle`) the row. */
export interface LegendItemControls {
    /** This row's series is toggled off. */
    isHidden: boolean
    /** This row's group is the only visible one — i.e. it is currently isolated. */
    isOnlyVisible: boolean
    /** No row is toggled off. */
    areAllVisible: boolean
    /** Whether isolating does anything: it needs more than one visibility group, an interactive
     *  legend, and — when the legend is controlled — an `onSetHiddenSeries` to write through. When
     *  false, a plain click falls back to toggling this one series. */
    canIsolate: boolean
    /** Add or remove just this series, as a ⌘/Ctrl-click does. */
    toggle: () => void
    /** Show only this series — or show all of them when this one is already the only visible one.
     *  What a plain click does. */
    isolate: () => void
    /** Hide every series, or show all when any is hidden. */
    toggleAll: () => void
}

/** Props to spread onto `<ChartLegend>` (everything except `children` and `legendDataAttr`). */
export interface ChartLegendRenderProps {
    show: boolean
    items: LegendItem[]
    position: NonNullable<ChartLegendConfig['position']>
    align: ChartLegendConfig['align']
    gap: ChartLegendConfig['gap']
    onItemClick?: (key: string, modifiers: LegendItemClickModifiers) => void
    hiddenKeys: string[]
    renderItem?: (defaultNode: ReactNode, item: LegendItem) => ReactNode
}

export interface ChartLegendState<Meta> {
    /** Series with toggled-off entries marked excluded — feed this into the chart's renderer. */
    visibleSeries: Series<Meta>[]
    /** Spread onto `<ChartLegend>`; the legend still lists hidden series (dimmed) so they restore. */
    legendProps: ChartLegendRenderProps
}

/** Shared plumbing for the multi-series charts' built-in legend. Manages the toggled-off keys
 *  (uncontrolled by default, controlled when `config.hiddenKeys` is set), derives the dimmed
 *  legend items from the *original* series (so hidden ones stay clickable), and returns the
 *  series to actually render with hidden entries excluded. Pass `items` to override the derived
 *  legend rows (e.g. a slope chart's per-series change labels). */
export function useChartLegend<Meta>(
    series: Series<Meta>[],
    theme: ChartTheme,
    config: ChartLegendConfig | undefined,
    items?: LegendItem[]
): ChartLegendState<Meta> {
    const controlledKeys = config?.hiddenKeys
    const [internalKeys, setInternalKeys] = useState<string[]>(() => config?.defaultHiddenKeys ?? [])
    const hiddenKeys = controlledKeys ?? internalKeys

    const onToggleSeries = config?.onToggleSeries
    const toggle = useCallback(
        (key: string) => {
            onToggleSeries?.(key, !hiddenKeys.includes(key))
            if (controlledKeys === undefined) {
                setInternalKeys((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]))
            }
        },
        [controlledKeys, hiddenKeys, onToggleSeries]
    )

    const hiddenSet = useMemo(() => new Set(hiddenKeys), [hiddenKeys])
    const visibleSeries = useMemo(() => applyHiddenSeries(series, hiddenSet), [series, hiddenSet])
    const derivedItems = useMemo(() => items ?? legendItemsFromSeries(series, theme), [items, series, theme])

    const interactive = config?.interactive ?? true

    // The rows the user can see, which is what "all" and "the others" mean to them — narrower than
    // `series`, which also carries derived overlays (CI bands, trend lines) that get no legend row.
    const rowKeys = useMemo(() => derivedItems.map((item) => item.key), [derivedItems])

    // "The others" is a question about visibility, not about rows, and a consumer can store one
    // visibility bit for several rows (see `visibilityGroupKey`). Resolve every row to its group
    // once so isolating, `canIsolate`, and `isOnlyVisible` all agree on what a distinct series is.
    const visibilityGroupKey = config?.visibilityGroupKey
    const groupByRow = useMemo(() => {
        const groups = new Map<string, string>()
        rowKeys.forEach((key) => groups.set(key, visibilityGroupKey?.(key) ?? key))
        return groups
    }, [rowKeys, visibilityGroupKey])
    const groupCount = useMemo(() => new Set(groupByRow.values()).size, [groupByRow])

    // Isolating and hiding-all replace the whole hidden set in one go, so a controlled legend needs
    // `onSetHiddenSeries`: the per-series `onToggleSeries` can't express it as a single update.
    const onSetHiddenSeries = config?.onSetHiddenSeries
    const setHidden = useCallback(
        (next: string[]) => {
            onSetHiddenSeries?.(next)
            if (controlledKeys === undefined) {
                setInternalKeys(next)
            }
        },
        [controlledKeys, onSetHiddenSeries]
    )

    const canSetBulk = controlledKeys === undefined || onSetHiddenSeries !== undefined
    const canIsolate = interactive && canSetBulk && groupCount > 1

    const isolate = useCallback(
        (key: string) => {
            const group = groupByRow.get(key)
            const others = rowKeys.filter((k) => groupByRow.get(k) !== group)
            const alreadyIsolated = others.length > 0 && !hiddenSet.has(key) && others.every((k) => hiddenSet.has(k))
            setHidden(alreadyIsolated ? [] : others)
        },
        [rowKeys, groupByRow, hiddenSet, setHidden]
    )

    const toggleAll = useCallback(() => {
        const allVisible = rowKeys.every((k) => !hiddenSet.has(k))
        setHidden(allVisible ? [...rowKeys] : [])
    }, [rowKeys, hiddenSet, setHidden])

    // Grafana's legend model: a plain click isolates (and clicking the isolated row restores all),
    // ⌘/Ctrl-click builds a selection one series at a time. Picking one series out of twenty is the
    // common case, and it costs one click here instead of nineteen.
    // A touch screen has no ⌘/Ctrl/Shift, so the additive gesture is unreachable and isolate-on-tap
    // would strand the user on one series with no way to add a second. Tap toggles there instead, so
    // taps build any subset the way the checkbox legend table does. Isolate stays on the row menu.
    const handleItemClick = useCallback(
        (key: string, { additive }: LegendItemClickModifiers) => {
            if (additive || !canIsolate || isCoarsePointer()) {
                toggle(key)
                return
            }
            isolate(key)
        },
        [canIsolate, toggle, isolate]
    )

    const consumerRenderItem = config?.renderItem
    const renderItem = useMemo(() => {
        if (!consumerRenderItem) {
            return undefined
        }
        const visibleRows = rowKeys.filter((k) => !hiddenSet.has(k))
        const visibleGroups = new Set(visibleRows.map((k) => groupByRow.get(k)))
        return (defaultNode: ReactNode, item: LegendItem): ReactNode =>
            consumerRenderItem(defaultNode, item, {
                isHidden: hiddenSet.has(item.key),
                isOnlyVisible: groupCount > 1 && visibleGroups.size === 1 && !hiddenSet.has(item.key),
                areAllVisible: visibleRows.length === rowKeys.length,
                canIsolate,
                toggle: () => toggle(item.key),
                isolate: () => isolate(item.key),
                toggleAll,
            })
    }, [consumerRenderItem, rowKeys, groupByRow, groupCount, hiddenSet, canIsolate, toggle, isolate, toggleAll])

    return {
        visibleSeries,
        legendProps: {
            show: config?.show ?? false,
            items: derivedItems,
            position: config?.position ?? 'bottom',
            align: config?.align,
            gap: config?.gap,
            onItemClick: interactive ? handleItemClick : undefined,
            hiddenKeys,
            renderItem,
        },
    }
}
