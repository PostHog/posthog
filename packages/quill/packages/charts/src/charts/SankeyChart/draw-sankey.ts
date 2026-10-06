import { color as d3Color } from 'd3-color'

import { mixColors } from '../../core/color-utils'
import type { SankeyChartLayout, SankeyHit, SankeyLinkDatum, SankeyNodeDatum } from './sankey-data'

export interface DrawSankeyOptions {
    linkOpacity: number
}

/** Ribbon opacity while it, or a node it touches, is hovered. */
const HOVER_LINK_OPACITY = 0.85
/** The rest of the graph fades toward the background so the hovered flow stands out. */
const HOVER_DIM_AMOUNT = 0.55
const HOVER_HIGHLIGHT_TARGET = '#ffffff'
const HOVER_HIGHLIGHT_AMOUNT = 0.15
const HOVER_DIM_TARGET_FALLBACK = '#ffffff'

function traceLink(ctx: CanvasRenderingContext2D, link: SankeyLinkDatum): void {
    const x0 = link.source.x1
    const x1 = link.target.x0
    const xm = (x0 + x1) / 2
    ctx.beginPath()
    ctx.moveTo(x0, link.y0)
    ctx.bezierCurveTo(xm, link.y0, xm, link.y1, x1, link.y1)
}

function strokeLink(ctx: CanvasRenderingContext2D, link: SankeyLinkDatum, color: string, opacity: number): void {
    traceLink(ctx, link)
    ctx.save()
    ctx.globalAlpha *= opacity
    ctx.strokeStyle = color
    // A sub-pixel ribbon disappears against the node it leaves; keep every flow visible.
    ctx.lineWidth = Math.max(1, link.width)
    ctx.stroke()
    ctx.restore()
}

function fillNode(ctx: CanvasRenderingContext2D, node: SankeyNodeDatum, color: string): void {
    ctx.fillStyle = color
    ctx.fillRect(node.x0, node.y0, node.x1 - node.x0, Math.max(1, node.y1 - node.y0))
}

/** Static layer: every ribbon under every node, in input order. */
export function drawSankey(ctx: CanvasRenderingContext2D, layout: SankeyChartLayout, options: DrawSankeyOptions): void {
    for (const link of layout.links) {
        strokeLink(ctx, link, link.color, options.linkOpacity)
    }
    for (const node of layout.nodes) {
        fillNode(ctx, node, node.color)
    }
}

export interface SankeyActiveFlow {
    hit: SankeyHit
    links: Set<SankeyLinkDatum>
    nodes: Set<SankeyNodeDatum>
}

/** The hovered node or ribbon plus everything connected to it, or `null` when nothing is hovered. */
export function sankeyActiveFlow(layout: SankeyChartLayout, hit: SankeyHit | null): SankeyActiveFlow | null {
    if (!hit) {
        return null
    }
    const links = new Set<SankeyLinkDatum>()
    const nodes = new Set<SankeyNodeDatum>()
    if (hit.kind === 'node') {
        const node = layout.nodes[hit.index]
        nodes.add(node)
        for (const link of layout.links) {
            if (link.source === node || link.target === node) {
                links.add(link)
                nodes.add(link.source)
                nodes.add(link.target)
            }
        }
    } else {
        const link = layout.links[hit.index]
        links.add(link)
        nodes.add(link.source)
        nodes.add(link.target)
    }
    return { hit, links, nodes }
}

/** A color `mixColors` can interpolate, or `null`. d3-color cannot parse modern CSS syntax such as
 *  `hsl(235deg 8% 15%)` or `oklch(...)`, so those go through the canvas, which serializes any color
 *  it accepts to hex or rgba. An invalid color leaves `fillStyle` unchanged, so two different
 *  sentinels tell it apart from a valid one. */
function parseableColor(ctx: CanvasRenderingContext2D, color: string): string | null {
    if (d3Color(color)) {
        return color
    }
    const previous = ctx.fillStyle
    const read = (sentinel: string): string => {
        ctx.fillStyle = sentinel
        ctx.fillStyle = color
        return String(ctx.fillStyle)
    }
    const first = read('#000000')
    const second = read('#ffffff')
    ctx.fillStyle = previous
    return first === second && d3Color(first) ? first : null
}

/** Hover layer: dims the graph toward the background, then repaints the active flow at full
 *  strength. Returns false when nothing is hovered. */
export function drawSankeyHover(
    ctx: CanvasRenderingContext2D,
    layout: SankeyChartLayout,
    flow: SankeyActiveFlow | null,
    options: DrawSankeyOptions & { backgroundColor?: string; progress: number }
): boolean {
    if (!flow) {
        return false
    }
    const { hit, links: activeLinks, nodes: activeNodes } = flow
    const dimTarget = parseableColor(ctx, options.backgroundColor || HOVER_DIM_TARGET_FALLBACK)
    const dim = options.progress * HOVER_DIM_AMOUNT

    // The dim fill must be opaque: a translucent repaint composites over the full-color static
    // layer and does not dim at all. A ribbon with nothing parseable to mix is left to the static
    // layer: any repaint over it would either darken it or paint it in the background color.
    for (const link of layout.links) {
        if (activeLinks.has(link) || !dimTarget) {
            continue
        }
        const linkColor = parseableColor(ctx, link.color)
        if (linkColor) {
            const resting = mixColors(dimTarget, linkColor, options.linkOpacity)
            // Fading the opaque dim in with progress keeps the first frame identical to the static layer.
            strokeLink(ctx, link, mixColors(resting, dimTarget, dim), options.progress)
        }
    }
    for (const link of activeLinks) {
        const opacity = options.linkOpacity + (HOVER_LINK_OPACITY - options.linkOpacity) * options.progress
        strokeLink(ctx, link, link.color, opacity)
    }
    // Nodes go last so a ribbon that skips a column never paints over the node it passes behind.
    for (const node of layout.nodes) {
        if (!activeNodes.has(node) && dimTarget) {
            fillNode(ctx, node, mixColors(node.color, dimTarget, dim))
        }
    }
    for (const node of activeNodes) {
        const highlight = hit.kind === 'node' && node === layout.nodes[hit.index]
        const color = highlight
            ? mixColors(node.color, HOVER_HIGHLIGHT_TARGET, HOVER_HIGHLIGHT_AMOUNT * options.progress)
            : node.color
        fillNode(ctx, node, color)
    }
    return true
}
