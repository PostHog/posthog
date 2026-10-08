import React, { useCallback, useMemo } from 'react'

import { ChartHoverContext, ChartLayoutContext } from '../../core/chart-context'
import type { ChartHoverContextValue, ChartLayoutContextValue } from '../../core/chart-context'
import { ChartShell, useCanvasBounds } from '../../core/chart-shell'
import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import { resolveCssColor } from '../../core/color-utils'
import { useChartCanvas } from '../../core/hooks/useChartCanvas'
import { useChartDraw } from '../../core/hooks/useChartDraw'
import { applyMarginOverride } from '../../core/hooks/useChartMargins'
import type { ChartDrawArgs, ChartMargins, ChartScales } from '../../core/types'
import { defaultResolveValue } from '../../core/types'
import { Tooltip } from '../../overlays/Tooltip'
import { PieTooltip } from '../PieChart/PieTooltip'
import { drawSankey, drawSankeyHover, emphasisForHighlight, emphasisForHit } from './draw-sankey'
import type { SankeyEmphasis } from './draw-sankey'
import { SankeyLayoutContext } from './sankey-context'
import type { SankeyLayoutContextValue } from './sankey-context'
import { computeSankeyLayout, defaultValueFormatter, hoverIndexToHit } from './sankey-data'
import type { SankeyChartLayout, SankeyLinkInput, SankeyNodeInput } from './sankey-data'
import { outsideLabelWidth, sankeyLabelBoxes } from './sankey-labels'
import type { SankeyLabelBox } from './sankey-labels'
import { SankeyColumnLabels } from './SankeyColumnLabels'
import { SankeyNodeLabels } from './SankeyNodeLabels'
import type { SankeyChartProps, SankeyTooltipContext } from './types'
import { useSankeyInteraction } from './useSankeyInteraction'

const DEFAULT_NODE_WIDTH = 12
const DEFAULT_NODE_PADDING = 8
const DEFAULT_LINK_OPACITY = 0.4
const HOVER_ANIMATION_MS = 150
const BASE_MARGINS: ChartMargins = { top: 8, right: 8, bottom: 8, left: 8 }
/** Room for the column header row above the plot. */
const COLUMN_LABEL_HEIGHT = 18
const DEFAULT_LABEL_COLOR = 'rgba(0, 0, 0, 0.7)'

const NO_SCALES: ChartScales = { x: () => undefined, y: () => 0, yTicks: () => [] }

/** Changes whenever the layout could validate differently, so a corrected graph clears the error. */
function graphKey(
    nodes: SankeyNodeInput<unknown>[],
    links: SankeyLinkInput<unknown>[],
    config: SankeyChartProps['config']
): string {
    // Structured serialization: ids are free-form strings, so a delimiter inside one must not collide.
    // JSON writes both NaN and a missing pin as null, so pins go in as strings to keep them apart.
    // The type goes in too, so a rejected '1' and a corrected 1 do not share a key.
    return JSON.stringify([
        nodes.map((node) => [node.id, typeof node.column, String(node.column)]),
        links.map(({ source, target, value }) => [source, target, value]),
        [config?.nodeWidth, config?.nodePadding, config?.nodeAlign, config?.preserveNodeOrder],
    ])
}

/** Used when `theme.colors` is empty, as `Heatmap` does for its accent. */
const FALLBACK_NODE_COLOR = '#1d4aff'

export function SankeyChart<NodeMeta = unknown, LinkMeta = NodeMeta>({
    onError,
    ...rest
}: SankeyChartProps<NodeMeta, LinkMeta>): React.ReactElement {
    return (
        <ChartErrorBoundary onError={onError} resetKey={graphKey(rest.nodes, rest.links, rest.config)}>
            <SankeyChartInner {...rest} />
        </ChartErrorBoundary>
    )
}

function SankeyChartInner<NodeMeta = unknown, LinkMeta = NodeMeta>({
    nodes,
    links,
    theme,
    config,
    tooltip,
    onNodeClick,
    onLinkClick,
    onHoverChange,
    highlight,
    className,
    dataAttr,
    children,
}: Omit<SankeyChartProps<NodeMeta, LinkMeta>, 'onError'>): React.ReactElement {
    const {
        nodeWidth = DEFAULT_NODE_WIDTH,
        nodePadding = DEFAULT_NODE_PADDING,
        nodeAlign = 'justify',
        preserveNodeOrder = false,
        columnLabels,
        showNodeLabels = true,
        lastColumnLabels = 'inside',
        showNodeValues = false,
        linkOpacity: configuredLinkOpacity = DEFAULT_LINK_OPACITY,
        valueFormatter = defaultValueFormatter,
        tooltip: tooltipConfig,
        margins: marginsOverride,
    } = config ?? {}
    const linkOpacity = Number.isFinite(configuredLinkOpacity)
        ? Math.min(1, Math.max(0, configuredLinkOpacity))
        : DEFAULT_LINK_OPACITY
    const showTooltip = tooltipConfig?.enabled !== false
    const hasColumnLabels = !!columnLabels && columnLabels.length > 0

    const outsideWidth = useMemo(
        () =>
            showNodeLabels && lastColumnLabels === 'outside'
                ? outsideLabelWidth(nodes, links, nodeAlign, showNodeValues, valueFormatter)
                : 0,
        [showNodeLabels, lastColumnLabels, nodes, links, nodeAlign, showNodeValues, valueFormatter]
    )

    const margins = useMemo<ChartMargins>(() => {
        const applied = marginsOverride ? applyMarginOverride(BASE_MARGINS, marginsOverride) : BASE_MARGINS
        // Column headers are sized for their room, so an override cannot take it away.
        return { ...applied, top: applied.top + (hasColumnLabels ? COLUMN_LABEL_HEIGHT : 0) }
    }, [hasColumnLabels, marginsOverride])

    const { canvasRef, overlayCanvasRef, wrapperRef, dimensions, ctx, overlayCtx } = useChartCanvas({ margins })

    // `outside` labels take their room from the plot, capped at half of it, so a chart narrower
    // than the labels still has nodes to draw and the labels truncate instead.
    const outsideRoom = dimensions ? Math.min(outsideWidth, Math.floor(dimensions.plotWidth / 2)) : 0
    const plot = useMemo(
        () =>
            dimensions
                ? {
                      plotLeft: dimensions.plotLeft,
                      plotTop: dimensions.plotTop,
                      plotWidth: dimensions.plotWidth - outsideRoom,
                      plotHeight: dimensions.plotHeight,
                  }
                : { plotLeft: 0, plotTop: 0, plotWidth: 0, plotHeight: 0 },
        [dimensions, outsideRoom]
    )

    // Nodes that share a label share a palette slot, so the same tool in two columns keeps one hue.
    const colorForLabel = useMemo(() => {
        const slots = new Map<string, string>()
        for (const node of nodes) {
            if (node.color) {
                continue
            }
            const label = node.label ?? node.id
            if (!slots.has(label)) {
                slots.set(label, theme.colors[slots.size % theme.colors.length] || FALLBACK_NODE_COLOR)
            }
        }
        return (label: string): string => slots.get(label) ?? (theme.colors[0] || FALLBACK_NODE_COLOR)
    }, [nodes, theme.colors])

    const layout = useMemo<SankeyChartLayout<NodeMeta, LinkMeta>>(
        () =>
            computeSankeyLayout<NodeMeta, LinkMeta>({
                nodes,
                links,
                plot,
                nodeWidth,
                nodePadding,
                nodeAlign,
                preserveNodeOrder,
                colorForLabel,
                resolveColor: resolveCssColor,
            }),
        [nodes, links, plot, nodeWidth, nodePadding, nodeAlign, preserveNodeOrder, colorForLabel]
    )

    // A controlled highlight paints on the static layer, so a change to it is a full repaint
    // rather than a hover animation frame. The graph is small enough that this is cheap, and it
    // keeps the hover overlay free to stay dark while the host owns emphasis.
    const emphasis = useMemo(
        () => (highlight ? emphasisForHighlight(layout as SankeyChartLayout<unknown, unknown>, highlight) : null),
        [layout, highlight]
    )
    const hasEmphasis = emphasis !== null

    // The shared draw loop keys repaints, including the hover overlay, on `scales` identity. The
    // overlay must also repaint when `linkOpacity` changes or a controlled highlight starts or
    // ends under a still cursor.
    const scales = useMemo<ChartScales | null>(
        () => (dimensions ? { ...NO_SCALES, _private: { __sankey: layout, linkOpacity, hasEmphasis } } : null),
        [dimensions, layout, linkOpacity, hasEmphasis]
    )

    const labelBoxes = useMemo<SankeyLabelBox[]>(
        () =>
            showNodeLabels
                ? sankeyLabelBoxes(layout as SankeyChartLayout<unknown, unknown>, {
                      showValues: showNodeValues,
                      valueFormatter,
                      lastColumnLabels,
                      outsideWidth: outsideRoom,
                  })
                : [],
        [showNodeLabels, layout, showNodeValues, valueFormatter, lastColumnLabels, outsideRoom]
    )

    const { hoverIndex, hoverPosition, tooltipCtx, handlers } = useSankeyInteraction<NodeMeta, LinkMeta>({
        layout,
        labelBoxes,
        canvasRef,
        wrapperRef,
        showTooltip,
        onNodeClick,
        onLinkClick,
        onHoverChange,
    })

    const drawStatic = useCallback(
        ({ ctx: drawCtx, theme: drawTheme }: ChartDrawArgs) =>
            drawSankey(drawCtx, layout as SankeyChartLayout<unknown, unknown>, {
                linkOpacity,
                emphasis,
                backgroundColor: drawTheme.backgroundColor,
            }),
        [layout, linkOpacity, emphasis]
    )
    // The hover fade repaints every frame; resolve the connected flow once per hovered item.
    const hoverEmphasisFor = useMemo(() => {
        let cached: { index: number; emphasis: SankeyEmphasis | null } | null = null
        return (index: number): SankeyEmphasis | null => {
            if (cached?.index !== index) {
                const untyped = layout as SankeyChartLayout<unknown, unknown>
                cached = { index, emphasis: emphasisForHit(untyped, hoverIndexToHit(untyped, index)) }
            }
            return cached.emphasis
        }
    }, [layout])
    const drawHover = useCallback(
        ({ ctx: drawCtx, hoverIndex: index, hoverProgress, theme: drawTheme }: ChartDrawArgs): boolean =>
            emphasis
                ? false
                : drawSankeyHover(drawCtx, layout as SankeyChartLayout<unknown, unknown>, hoverEmphasisFor(index), {
                      linkOpacity,
                      backgroundColor: drawTheme.backgroundColor,
                      progress: hoverProgress,
                  }),
        [layout, linkOpacity, emphasis, hoverEmphasisFor]
    )

    useChartDraw({
        ctx,
        overlayCtx,
        dimensions,
        scales,
        series: [],
        labels: [],
        hoverIndex,
        hoverPosition,
        theme,
        drawStatic,
        drawHover,
        hoverAnimationMs: HOVER_ANIMATION_MS,
    })

    const renderTooltip = useMemo(
        () =>
            tooltip ??
            ((tooltipContext: SankeyTooltipContext<NodeMeta, LinkMeta>): React.ReactNode => (
                <PieTooltip ctx={tooltipContext} valueFormatter={valueFormatter} />
            )),
        [tooltip, valueFormatter]
    )

    const canvasBounds = useCanvasBounds(canvasRef)
    const layoutValue = useMemo<ChartLayoutContextValue | null>(() => {
        if (!scales || !dimensions) {
            return null
        }
        return {
            scales,
            dimensions: { ...dimensions, plotWidth: plot.plotWidth },
            labels: [],
            series: [],
            theme,
            resolvePositionValue: defaultResolveValue,
            canvasBounds,
            axis: { orientation: 'vertical', xTickFormatter: undefined, isPercent: false },
            yGutters: [],
        }
    }, [scales, dimensions, plot.plotWidth, theme, canvasBounds])
    const sankeyValue = useMemo<SankeyLayoutContextValue<NodeMeta, LinkMeta>>(
        () => ({ layout, canvasBounds }),
        [layout, canvasBounds]
    )
    const hoverValue = useMemo<ChartHoverContextValue>(() => ({ hoverIndex }), [hoverIndex])

    const ariaLabel = `Sankey chart with ${layout.nodes.length} nodes and ${layout.links.length} links`
    const labelColor = theme.axisColor ?? DEFAULT_LABEL_COLOR
    const clickable = hoverIndex >= 0 && !!(onNodeClick || onLinkClick)

    return (
        <ChartLayoutContext.Provider value={layoutValue}>
            <SankeyLayoutContext.Provider value={sankeyValue as SankeyLayoutContextValue}>
                <ChartHoverContext.Provider value={hoverValue}>
                    <ChartShell
                        wrapperRef={wrapperRef}
                        canvasRef={canvasRef}
                        overlayCanvasRef={overlayCanvasRef}
                        className={className}
                        dataAttr={dataAttr}
                        pointer={clickable}
                        ariaLabel={ariaLabel}
                        handlers={handlers}
                        showOverlay={!!dimensions}
                    >
                        {hasColumnLabels ? (
                            <SankeyColumnLabels labels={columnLabels} color={labelColor} trailingRoom={outsideRoom} />
                        ) : null}
                        {showNodeLabels ? <SankeyNodeLabels boxes={labelBoxes} color={labelColor} /> : null}
                        {children}
                        {tooltipCtx && showTooltip ? (
                            <Tooltip
                                context={tooltipCtx}
                                renderTooltip={renderTooltip as never}
                                placement={tooltipConfig?.placement ?? 'cursor'}
                            />
                        ) : null}
                    </ChartShell>
                </ChartHoverContext.Provider>
            </SankeyLayoutContext.Provider>
        </ChartLayoutContext.Provider>
    )
}
