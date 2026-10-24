/* eslint-disable react/forbid-dom-props -- the scroll viewport and canvas host are sized from the tree depth at runtime */
import React, { useCallback, useDeferredValue, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'

import { ChartHoverContext, ChartLayoutContext } from '../../core/chart-context'
import type { ChartHoverContextValue, ChartLayoutContextValue } from '../../core/chart-context'
import { ChartShell, useCanvasBounds } from '../../core/chart-shell'
import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import { clearAndPrepare } from '../../core/hooks/clearCanvas'
import { useChartCanvas } from '../../core/hooks/useChartCanvas'
import { useLatest } from '../../core/hooks/useLatest'
import { prefersReducedMotion } from '../../core/motion'
import { markPaintDone, markPaintPending } from '../../core/paint-state'
import { monotonicNow } from '../../core/time'
import type { ChartMargins, ChartScales } from '../../core/types'
import { defaultResolveValue } from '../../core/types'
import { Tooltip } from '../../overlays/Tooltip'
import { cellRect, drawFlame, drawFlameHover, LabelFitter } from './draw-flame'
import { computeFlameColors, FlameShades, resolveColorBy, resolveInk } from './flame-colors'
import {
    ancestorPath,
    buildFlameTree,
    cellAt,
    computeFlameCells,
    depthAtY,
    type FlameCell,
    type FlameDiffOptions,
    type FlameFocus,
    type FlameRowGeometry,
    type FlameTree,
    type FlameWindow,
    focusRowCount,
    focusWindow,
    nodeDatum,
    searchFlame,
    visibleDepths,
} from './flame-layout'
import { FlameGraphHeader, type FlameCrumb } from './FlameGraphHeader'
import { FlameLegend } from './FlameLegend'
import { FlameTooltip } from './FlameTooltip'
import type { FlameBundleDatum, FlameGraphProps, FlameHit, FlameNodeDatum, FlameTooltipContext } from './types'

const DEFAULT_ROW_HEIGHT = 22
const DEFAULT_MAX_HEIGHT = 480
const DEFAULT_THRESHOLD = 0.1
const FOCUS_ANIMATION_MS = 280
const ZERO_MARGINS: ChartMargins = { top: 0, right: 0, bottom: 0, left: 0 }
const NO_SCALES: ChartScales = { x: () => undefined, y: () => 0, yTicks: () => [] }

const defaultValueFormatter = (value: number): string => value.toLocaleString()

const easeInOutCubic = (t: number): number => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2)

/** Focus by id rather than index, so it survives a data update that keeps the node. */
type FocusKey = { kind: 'node'; id: string } | { kind: 'bundle'; first: string; last: string } | null

/** Resolves a focus against `tree`. A node with no width cannot be zoomed into, so it resolves to
 *  the whole graph. A bundle whose ends no longer share a parent falls back to that parent. */
function keyToFocus(tree: FlameTree<unknown>, key: FocusKey): FlameFocus {
    const zoomable = (index: number | undefined): index is number =>
        index !== undefined && index >= 0 && tree.x1[index] > tree.x0[index]
    if (key?.kind === 'node') {
        const index = tree.idToIndex.get(key.id)
        return zoomable(index) ? { kind: 'node', index } : null
    }
    if (key?.kind === 'bundle') {
        const first = tree.idToIndex.get(key.first)
        const last = tree.idToIndex.get(key.last)
        if (first !== undefined && last !== undefined && first <= last && tree.parent[first] === tree.parent[last]) {
            return { kind: 'bundle', first, last }
        }
        const parent = first !== undefined ? tree.parent[first] : -1
        return zoomable(parent) ? { kind: 'node', index: parent } : null
    }
    return null
}

function idToKey(id: string | null | undefined): FocusKey {
    return id ? { kind: 'node', id } : null
}

function bundleDatum<Meta>(
    tree: FlameTree<Meta>,
    first: number,
    last: number,
    diff: FlameDiffOptions
): FlameBundleDatum<Meta> {
    const nodes: FlameNodeDatum<Meta>[] = []
    let descendantCount = 0
    let value = 0
    for (let i = first; i <= last; i++) {
        nodes.push(nodeDatum(tree, i, diff))
        descendantCount += tree.subtreeSize[i]
        value += tree.value[i]
    }
    return { parent: nodeDatum(tree, tree.parent[first], diff), nodes, descendantCount, value }
}

/** Runs `callback` on the next frame and keeps its id in `ref` until it runs. A frame that runs
 *  synchronously (the test shim) never leaves a stale id behind. */
function scheduleFrame(ref: React.MutableRefObject<number | null>, callback: () => void): void {
    let ran = false
    const id = requestAnimationFrame(() => {
        ran = true
        ref.current = null
        callback()
    })
    if (!ran) {
        ref.current = id
    }
}

interface HoverState {
    cell: FlameCell
    /** The tree the cell's indices point into. */
    tree: FlameTree<unknown>
    x: number
    y: number
}

export function FlameGraph<Meta = unknown>({ onError, ...rest }: FlameGraphProps<Meta>): React.ReactElement {
    return (
        <ChartErrorBoundary onError={onError} resetKey={rest.data}>
            <FlameGraphInner {...rest} />
        </ChartErrorBoundary>
    )
}

function FlameGraphInner<Meta = unknown>({
    data,
    theme,
    config,
    search,
    defaultFocusedId,
    tooltip,
    onNodeClick,
    onFocusChange,
    className,
    dataAttr,
}: Omit<FlameGraphProps<Meta>, 'onError'>): React.ReactElement {
    const {
        colorBy: requestedColorBy,
        diff: diffConfig,
        valueFormatter = defaultValueFormatter,
        rowHeight: requestedRowHeight = DEFAULT_ROW_HEIGHT,
        height = 'auto',
        maxHeight = DEFAULT_MAX_HEIGHT,
        direction = 'top-down',
        clickToFocus = true,
        showBreadcrumb = true,
        showLegend = true,
        tooltip: tooltipConfig,
    } = config ?? {}
    const rowHeight = Math.max(8, requestedRowHeight)
    const showTooltip = tooltipConfig?.enabled !== false
    const threshold = Math.max(0, diffConfig?.threshold ?? DEFAULT_THRESHOLD)
    const minCount = Math.max(0, diffConfig?.minCount ?? 0)

    const tree = useMemo(() => buildFlameTree(data), [data])
    const colorBy = resolveColorBy(tree, requestedColorBy)
    const diff = useMemo<FlameDiffOptions>(
        () => ({ comparing: colorBy === 'diff', threshold, minCount }),
        [colorBy, threshold, minCount]
    )

    // `useChartTheme` returns an equal palette in a new array on any class change on <html>, so key
    // the colors on the values rather than the array identity.
    const paletteKey = theme.colors.join('\n')
    const ink = useMemo(
        () => resolveInk(theme, diffConfig?.slowerColor, diffConfig?.fasterColor),
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [paletteKey, theme.backgroundColor, theme.tooltipColor, diffConfig?.slowerColor, diffConfig?.fasterColor]
    )
    const colors = useMemo(
        () => computeFlameColors(tree, colorBy, theme, ink, diff),
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [tree, colorBy, paletteKey, ink, diff]
    )
    const shades = useMemo(() => new FlameShades(ink), [ink])
    const fitter = useMemo(() => new LabelFitter(), [])
    // Deferred so typing in a host's search box stays responsive while a large tree is searched.
    const deferredSearch = useDeferredValue(search)
    const searchResult = useMemo(() => searchFlame(tree, deferredSearch), [tree, deferredSearch])

    const [focusKey, setFocusKey] = useState<FocusKey>(() => idToKey(defaultFocusedId))
    const isFirstFocusProp = useRef(true)
    useEffect(() => {
        if (isFirstFocusProp.current) {
            isFirstFocusProp.current = false
            return
        }
        setFocusKey(idToKey(defaultFocusedId))
    }, [defaultFocusedId])
    const focus = useMemo(() => keyToFocus(tree, focusKey), [tree, focusKey])
    const target = useMemo(() => focusWindow(tree, focus), [tree, focus])
    const focusNodeIndex = focus?.kind === 'node' ? focus.index : focus ? tree.parent[focus.first] : -1
    const focusPath = useMemo(
        () => (focusNodeIndex >= 0 ? ancestorPath(tree, focusNodeIndex) : []),
        [tree, focusNodeIndex]
    )
    const ancestors = useMemo(
        () => new Set(focus?.kind === 'node' ? focusPath.slice(0, -1) : focusPath),
        [focus, focusPath]
    )

    const { canvasRef, overlayCanvasRef, wrapperRef, dimensions, ctx, overlayCtx } = useChartCanvas({
        margins: ZERO_MARGINS,
    })

    // Rows below the deepest drawable node would be blank scroll room, so the height stops there.
    // Before the first measure, fall back to the deepest node in the focus.
    const plotWidth = dimensions?.width ?? 0
    const targetRows = useMemo(() => {
        if (plotWidth <= 0) {
            return Math.max(1, focusRowCount(tree, focus))
        }
        const cells = computeFlameCells(tree, target, plotWidth, 0, tree.maxDepth)
        return cells.length > 0 ? cells[cells.length - 1].depth + 1 : 1
    }, [tree, focus, target, plotWidth])
    // While zooming out to a shallower subtree, keep the taller height until the animation ends,
    // so the rows being animated away are not cut off mid-flight.
    const [heldRows, setHeldRows] = useState(0)
    const rowCount = Math.max(targetRows, heldRows)
    const contentHeight = rowCount * rowHeight

    const scrollRef = useRef<HTMLDivElement | null>(null)
    const [fillHeight, setFillHeight] = useState(0)
    useLayoutEffect(() => {
        const el = scrollRef.current
        if (height !== 'fill' || !el) {
            return
        }
        const measure = (): void => setFillHeight(el.getBoundingClientRect().height)
        measure()
        if (typeof ResizeObserver === 'undefined') {
            return
        }
        const observer = new ResizeObserver(measure)
        observer.observe(el)
        return () => observer.disconnect()
    }, [height])
    const viewportHeight =
        height === 'fill'
            ? Math.max(rowHeight, fillHeight)
            : typeof height === 'number'
              ? Math.max(rowHeight, height)
              : Math.max(rowHeight, Math.min(contentHeight, maxHeight))

    // Bottom-up rows count up from the bottom of the viewport, so a viewport taller than the tree
    // keeps the roots on its bottom edge instead of above blank space.
    const geometryRows =
        direction === 'bottom-up' ? Math.max(rowCount, Math.floor(viewportHeight / rowHeight)) : rowCount
    const geometry = useMemo<FlameRowGeometry>(
        () => ({ rowHeight, rowCount: geometryRows, direction }),
        [rowHeight, geometryRows, direction]
    )

    const viewRef = useRef<FlameWindow>(target)
    const scrollTopRef = useRef(0)
    const cellsRef = useRef<{ cells: FlameCell[]; tree: FlameTree<unknown> | null }>({ cells: [], tree: null })
    const paintRafRef = useRef<number | null>(null)
    const animationRafRef = useRef<number | null>(null)
    const [hoverState, setHover] = useState<HoverState | null>(null)
    // A hover from before a data update points into the old tree, so it reads as no hover.
    const hover = hoverState?.tree === tree ? hoverState : null

    const paintInputs = useLatest({ tree, colors, shades, ink, fitter, geometry, searchResult, ancestors, theme })
    const paint = useCallback((): void => {
        if (!ctx) {
            return
        }
        const inputs = paintInputs.current
        if (!dimensions || inputs.theme.skipDraw) {
            markPaintDone(ctx.canvas)
            return
        }
        clearAndPrepare(ctx, dimensions)
        try {
            const scrollTop = scrollTopRef.current
            const [firstDepth, lastDepth] = visibleDepths(scrollTop, dimensions.height, inputs.geometry)
            const cells = computeFlameCells(inputs.tree, viewRef.current, dimensions.width, firstDepth, lastDepth)
            cellsRef.current = { cells, tree: inputs.tree }
            drawFlame(ctx, {
                tree: inputs.tree,
                cells,
                fills: inputs.colors.fills,
                marks: inputs.colors.marks,
                ink: inputs.ink,
                shades: inputs.shades,
                fitter: inputs.fitter,
                geometry: inputs.geometry,
                matches: inputs.searchResult?.matches ?? null,
                containsMatch: inputs.searchResult?.containsMatch ?? null,
                ancestors: inputs.ancestors,
                scrollTop,
                width: dimensions.width,
                pixelRatio: dimensions.width > 0 ? ctx.canvas.width / dimensions.width : 1,
            })
        } finally {
            ctx.restore()
            markPaintDone(ctx.canvas)
        }
    }, [ctx, dimensions, paintInputs])

    // Frames queued earlier, and the zoom animation, must draw with the dimensions of the latest
    // render: a zoom can grow the viewport while it animates.
    const paintRef = useLatest(paint)
    const requestPaint = useCallback((): void => {
        if (!ctx || paintRafRef.current !== null) {
            return
        }
        markPaintPending(ctx.canvas)
        scheduleFrame(paintRafRef, () => paintRef.current())
    }, [ctx, paintRef])

    useEffect(
        () => requestPaint(),
        [requestPaint, tree, colors, shades, searchResult, ancestors, geometry, theme.skipDraw]
    )

    const isFirstWindow = useRef(true)
    useEffect(() => {
        const from = viewRef.current
        if (animationRafRef.current !== null) {
            cancelAnimationFrame(animationRafRef.current)
            animationRafRef.current = null
        }
        const unchanged = from.x0 === target.x0 && from.x1 === target.x1
        if (isFirstWindow.current || unchanged || prefersReducedMotion() || theme.skipDraw) {
            isFirstWindow.current = false
            viewRef.current = target
            setHeldRows(0)
            requestPaint()
            return
        }
        setHover(null)
        const start = monotonicNow()
        const tick = (): void => {
            const t = Math.min(1, (monotonicNow() - start) / FOCUS_ANIMATION_MS)
            const eased = easeInOutCubic(t)
            viewRef.current = {
                x0: from.x0 + (target.x0 - from.x0) * eased,
                x1: from.x1 + (target.x1 - from.x1) * eased,
            }
            paintRef.current()
            if (t < 1) {
                scheduleFrame(animationRafRef, tick)
            } else {
                setHeldRows(0)
            }
        }
        scheduleFrame(animationRafRef, tick)
        // `requestPaint` changes with the canvas, and the zoom must not restart then.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [target])

    useEffect(
        () => () => {
            if (paintRafRef.current !== null) {
                cancelAnimationFrame(paintRafRef.current)
                paintRafRef.current = null
            }
            if (animationRafRef.current !== null) {
                cancelAnimationFrame(animationRafRef.current)
                animationRafRef.current = null
            }
        },
        []
    )

    const hoverRect = useMemo(
        () =>
            hover && dimensions && ctx
                ? cellRect(
                      hover.cell,
                      geometry,
                      scrollTopRef.current,
                      dimensions.width,
                      dimensions.width > 0 ? ctx.canvas.width / dimensions.width : 1
                  )
                : null,
        [hover?.cell, dimensions, ctx, geometry] // eslint-disable-line react-hooks/exhaustive-deps
    )
    useEffect(() => {
        if (!overlayCtx || !dimensions) {
            return
        }
        clearAndPrepare(overlayCtx, dimensions)
        try {
            if (hoverRect && !theme.skipDraw) {
                drawFlameHover(overlayCtx, hoverRect, ink)
            }
        } finally {
            overlayCtx.restore()
        }
    }, [overlayCtx, dimensions, hoverRect, ink, theme.skipDraw])

    const changeFocus = useCallback(
        (next: FocusKey): void => {
            setHeldRows(rowCount)
            setFocusKey(next)
            if (!onFocusChange) {
                return
            }
            const resolved = keyToFocus(tree, next)
            const index = resolved?.kind === 'node' ? resolved.index : resolved ? tree.parent[resolved.first] : -1
            onFocusChange(index >= 0 ? nodeDatum(tree, index, diff) : null)
        },
        [rowCount, onFocusChange, tree, diff]
    )

    const hitAt = useCallback(
        (clientX: number, clientY: number): HoverState | null => {
            const bounds = canvasRef.current?.getBoundingClientRect()
            if (!bounds) {
                return null
            }
            const x = clientX - bounds.left
            const y = clientY - bounds.top
            const depth = depthAtY(y + scrollTopRef.current, geometry)
            const { cells, tree: cellsTree } = cellsRef.current
            const cell = depth >= 0 ? cellAt(cells, depth, x) : null
            return cell && cellsTree ? { cell, x, y, tree: cellsTree } : null
        },
        [canvasRef, geometry]
    )

    const handlers = useMemo(
        () => ({
            onMouseMove: (event: React.MouseEvent<HTMLDivElement>): void => {
                if (animationRafRef.current !== null) {
                    return
                }
                setHover(hitAt(event.clientX, event.clientY))
            },
            onMouseLeave: (): void => setHover(null),
            onClick: (event: React.MouseEvent<HTMLDivElement>): void => {
                const hit = hitAt(event.clientX, event.clientY)
                if (!hit) {
                    return
                }
                const { cell } = hit
                if (cell.kind === 'bundle') {
                    changeFocus({ kind: 'bundle', first: tree.ids[cell.index], last: tree.ids[cell.last] })
                    return
                }
                const isFocused = focus?.kind === 'node' && focus.index === cell.index
                if (clickToFocus && !isFocused) {
                    changeFocus({ kind: 'node', id: tree.ids[cell.index] })
                }
                onNodeClick?.(nodeDatum(tree, cell.index, diff))
            },
        }),
        [hitAt, changeFocus, tree, focus, clickToFocus, onNodeClick, diff]
    )

    // Bottom-up graphs keep their roots in view, at the bottom of the scroll range.
    useLayoutEffect(() => {
        const el = scrollRef.current
        if (direction === 'bottom-up' && el) {
            el.scrollTop = el.scrollHeight
            scrollTopRef.current = el.scrollTop
        }
    }, [direction, contentHeight, tree])

    const onScroll = useCallback(
        (event: React.UIEvent<HTMLDivElement>): void => {
            scrollTopRef.current = event.currentTarget.scrollTop
            setHover(null)
            requestPaint()
        },
        [requestPaint]
    )

    const zoomOut = useCallback((): void => {
        if (!focus) {
            return
        }
        const parentIndex = focus.kind === 'node' ? tree.parent[focus.index] : tree.parent[focus.first]
        if (focus.kind === 'bundle') {
            changeFocus({ kind: 'node', id: tree.ids[parentIndex] })
        } else {
            changeFocus(parentIndex >= 0 ? { kind: 'node', id: tree.ids[parentIndex] } : null)
        }
    }, [focus, tree, changeFocus])

    const onKeyDown = useCallback(
        (event: React.KeyboardEvent<HTMLDivElement>): void => {
            if (event.key === 'Escape' && focus) {
                event.stopPropagation()
                zoomOut()
            }
        },
        [focus, zoomOut]
    )

    const crumbs = useMemo<FlameCrumb[]>(() => {
        const items: FlameCrumb[] = focusPath.map((index) => ({
            key: tree.ids[index],
            label: String(tree.nodes[index].name ?? ''),
            onSelect: () => changeFocus({ kind: 'node', id: tree.ids[index] }),
        }))
        if (focus?.kind === 'bundle') {
            items.push({ key: '\u0000bundle', label: `+${focus.last - focus.first + 1} more`, onSelect: () => {} })
        }
        return items
    }, [focusPath, focus, tree, changeFocus])

    const hit = useMemo<FlameHit<Meta> | null>(() => {
        if (!hover) {
            return null
        }
        const { cell } = hover
        return cell.kind === 'bundle'
            ? { kind: 'bundle', bundle: bundleDatum(tree, cell.index, cell.last, diff) }
            : { kind: 'node', node: nodeDatum(tree, cell.index, diff) }
    }, [hover?.cell, tree, diff]) // eslint-disable-line react-hooks/exhaustive-deps

    const canvasBounds = useCanvasBounds(canvasRef)
    const tooltipCtx = useMemo<FlameTooltipContext<Meta> | null>(() => {
        const bounds = canvasBounds()
        if (!hover || !hit || !bounds) {
            return null
        }
        const label = hit.kind === 'node' ? hit.node.name : `${hit.bundle.nodes.length} smaller nodes`
        const value = hit.kind === 'node' ? hit.node.value : hit.bundle.value
        const fill = hover.cell.kind === 'bundle' ? ink.neutral : colors.fills[hover.cell.index]
        const isFocused = focus?.kind === 'node' && hover.cell.kind === 'node' && focus.index === hover.cell.index
        return {
            dataIndex: hover.cell.index,
            label,
            seriesData: [
                {
                    series: { key: tree.ids[hover.cell.index], label, data: [value] },
                    value,
                    color: fill,
                },
            ],
            position: { x: hover.x, y: hover.y },
            hoverPosition: { x: hover.x, y: hover.y },
            canvasBounds: bounds,
            isPinned: false,
            hit,
            valueFormatter,
            comparing: colorBy === 'diff',
            canFocus: hover.cell.kind === 'bundle' || (clickToFocus && !isFocused),
        }
    }, [hover, hit, canvasBounds, ink, colors, focus, tree, valueFormatter, colorBy, clickToFocus])

    const renderTooltip = useMemo(
        () =>
            tooltip ??
            ((context: FlameTooltipContext<Meta>): React.ReactNode => <FlameTooltip ctx={context} ink={ink} />),
        [tooltip, ink]
    )

    const layoutValue = useMemo<ChartLayoutContextValue | null>(
        () =>
            dimensions
                ? {
                      scales: NO_SCALES,
                      dimensions,
                      labels: [],
                      series: [],
                      theme,
                      resolvePositionValue: defaultResolveValue,
                      canvasBounds,
                      axis: { orientation: 'vertical', xTickFormatter: undefined, isPercent: false },
                      yGutters: [],
                  }
                : null,
        [dimensions, theme, canvasBounds]
    )
    const hoverValue = useMemo<ChartHoverContextValue>(() => ({ hoverIndex: hover?.cell.index ?? -1 }), [hover])

    const isEmpty = tree.size === 0 || tree.x1[tree.rowStart[1] - 1] <= 0
    const clickable = !!hover && (hover.cell.kind === 'bundle' || clickToFocus || !!onNodeClick)
    const fillParent = height === 'fill'

    return (
        <ChartLayoutContext.Provider value={layoutValue}>
            <ChartHoverContext.Provider value={hoverValue}>
                <div
                    className={`flex flex-col gap-1.5 min-w-0 w-full ${fillParent ? 'h-full min-h-0' : ''} ${className ?? ''}`}
                    data-attr={dataAttr}
                    data-hog-charts-flame=""
                >
                    {showBreadcrumb && !isEmpty ? (
                        <FlameGraphHeader
                            crumbs={crumbs}
                            onReset={focus ? () => changeFocus(null) : null}
                            search={searchResult}
                        />
                    ) : null}
                    <div
                        ref={scrollRef}
                        className={`relative w-full overflow-y-auto overflow-x-hidden outline-none focus-visible:ring-2 focus-visible:ring-(--color-graph-crosshair) ${fillParent ? 'flex-1 min-h-0' : ''}`}
                        style={fillParent ? undefined : { height: viewportHeight }}
                        tabIndex={0}
                        onScroll={onScroll}
                        onKeyDown={onKeyDown}
                    >
                        <div className="relative w-full" style={{ height: Math.max(contentHeight, viewportHeight) }}>
                            <div className="sticky top-0 flex flex-col w-full" style={{ height: viewportHeight }}>
                                <ChartShell
                                    wrapperRef={wrapperRef}
                                    canvasRef={canvasRef}
                                    overlayCanvasRef={overlayCanvasRef}
                                    pointer={clickable}
                                    ariaLabel={`Flame graph with ${tree.size} nodes`}
                                    handlers={handlers}
                                    showOverlay={!!dimensions}
                                >
                                    {isEmpty ? (
                                        <div className="flex items-center justify-center w-full h-full text-xs text-(--color-graph-axis-label)">
                                            No data to show
                                        </div>
                                    ) : null}
                                    {tooltipCtx && showTooltip ? (
                                        <Tooltip
                                            context={tooltipCtx}
                                            renderTooltip={renderTooltip as never}
                                            placement="cursor"
                                        />
                                    ) : null}
                                </ChartShell>
                            </div>
                        </div>
                    </div>
                    {showLegend && colors.legend.length > 0 && !isEmpty ? (
                        <FlameLegend entries={colors.legend} ink={ink} />
                    ) : null}
                </div>
            </ChartHoverContext.Provider>
        </ChartLayoutContext.Provider>
    )
}
