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
import { drawSankey, drawSankeyHover } from './draw-sankey'
import { SankeyLayoutContext } from './sankey-context'
import type { SankeyLayoutContextValue } from './sankey-context'
import { computeSankeyLayout, defaultValueFormatter, hoverIndexToHit } from './sankey-data'
import type { SankeyChartLayout } from './sankey-data'
import { SankeyColumnLabels } from './SankeyColumnLabels'
import { SankeyNodeLabels } from './SankeyNodeLabels'
import { SankeyTooltip } from './SankeyTooltip'
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

export function SankeyChart<NodeMeta = unknown, LinkMeta = NodeMeta>({
    onError,
    ...rest
}: SankeyChartProps<NodeMeta, LinkMeta>): React.ReactElement {
    return (
        <ChartErrorBoundary onError={onError}>
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
        showNodeValues = false,
        linkOpacity = DEFAULT_LINK_OPACITY,
        valueFormatter = defaultValueFormatter,
        tooltip: tooltipConfig,
        margins: marginsOverride,
    } = config ?? {}
    const showTooltip = tooltipConfig?.enabled !== false
    const hasColumnLabels = !!columnLabels && columnLabels.length > 0

    const margins = useMemo<ChartMargins>(() => {
        const computed = hasColumnLabels
            ? { ...BASE_MARGINS, top: BASE_MARGINS.top + COLUMN_LABEL_HEIGHT }
            : BASE_MARGINS
        return marginsOverride ? applyMarginOverride(computed, marginsOverride) : computed
    }, [hasColumnLabels, marginsOverride])

    const { canvasRef, overlayCanvasRef, wrapperRef, dimensions, ctx, overlayCtx } = useChartCanvas({ margins })

    // Nodes that share a label share a palette slot, so the same tool in two columns keeps one hue.
    const colorForLabel = useMemo(() => {
        const slots = new Map<string, string>()
        for (const node of nodes) {
            const label = node.label ?? node.id
            if (!slots.has(label)) {
                slots.set(label, theme.colors[slots.size % theme.colors.length])
            }
        }
        return (label: string): string => slots.get(label) ?? theme.colors[0]
    }, [nodes, theme.colors])

    const layout = useMemo<SankeyChartLayout<NodeMeta, LinkMeta>>(
        () =>
            computeSankeyLayout<NodeMeta, LinkMeta>({
                nodes,
                links,
                plot: dimensions ?? { plotLeft: 0, plotTop: 0, plotWidth: 0, plotHeight: 0 },
                nodeWidth,
                nodePadding,
                nodeAlign,
                preserveNodeOrder,
                colorForLabel,
                resolveColor: resolveCssColor,
            }),
        [nodes, links, dimensions, nodeWidth, nodePadding, nodeAlign, preserveNodeOrder, colorForLabel]
    )

    // The shared draw loop keys repaints on `scales` identity, so wrap the layout in one.
    const scales = useMemo<ChartScales | null>(
        () => (dimensions ? { ...NO_SCALES, _private: { __sankey: layout } } : null),
        [dimensions, layout]
    )

    const { hoverIndex, hoverPosition, tooltipCtx, handlers } = useSankeyInteraction<NodeMeta, LinkMeta>({
        layout,
        canvasRef,
        wrapperRef,
        showTooltip,
        onNodeClick,
        onLinkClick,
    })

    const drawStatic = useCallback(
        ({ ctx: drawCtx }: ChartDrawArgs) =>
            drawSankey(drawCtx, layout as SankeyChartLayout<unknown, unknown>, { linkOpacity }),
        [layout, linkOpacity]
    )
    const drawHover = useCallback(
        ({ ctx: drawCtx, hoverIndex: index, hoverProgress, theme: drawTheme }: ChartDrawArgs): boolean =>
            drawSankeyHover(drawCtx, layout as SankeyChartLayout<unknown, unknown>, hoverIndexToHit(layout, index), {
                linkOpacity,
                backgroundColor: drawTheme.backgroundColor,
                progress: hoverProgress,
            }),
        [layout, linkOpacity]
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
                <SankeyTooltip ctx={tooltipContext} valueFormatter={valueFormatter} />
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
            dimensions,
            labels: [],
            series: [],
            theme,
            resolvePositionValue: defaultResolveValue,
            canvasBounds,
            axis: { orientation: 'vertical', xTickFormatter: undefined, isPercent: false },
            yGutters: [],
        }
    }, [scales, dimensions, theme, canvasBounds])
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
                        {hasColumnLabels ? <SankeyColumnLabels labels={columnLabels} color={labelColor} /> : null}
                        {showNodeLabels ? (
                            <SankeyNodeLabels
                                color={labelColor}
                                showValues={showNodeValues}
                                valueFormatter={valueFormatter}
                            />
                        ) : null}
                        {children}
                        {tooltipCtx && showTooltip ? (
                            <Tooltip context={tooltipCtx} renderTooltip={renderTooltip as never} placement="cursor" />
                        ) : null}
                    </ChartShell>
                </ChartHoverContext.Provider>
            </SankeyLayoutContext.Provider>
        </ChartLayoutContext.Provider>
    )
}
