import { mixColors } from '../../core/color-utils'
import type { SankeyChartLayout, SankeyHit, SankeyLinkDatum, SankeyNodeDatum } from './sankey-data'
import type { SankeyHighlight } from './types'

export interface DrawSankeyOptions {
    linkOpacity: number
}

/** The part of the graph that stays at full strength while the rest dims. */
export interface SankeyEmphasis {
    nodes: Set<SankeyNodeDatum>
    links: Set<SankeyLinkDatum>
    /** The node under the cursor, lightened a step further than the other active nodes. */
    focus?: SankeyNodeDatum
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

/** The hovered node with every ribbon it touches, or the hovered ribbon with its two ends. */
export function emphasisForHit(layout: SankeyChartLayout, hit: SankeyHit | null): SankeyEmphasis | null {
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
        return { nodes, links, focus: node }
    }
    const link = layout.links[hit.index]
    links.add(link)
    nodes.add(link.source)
    nodes.add(link.target)
    return { nodes, links }
}

/** Resolves a consumer's highlight to laid-out data. Ids and indices the layout does not know are
 *  ignored, so a highlight computed from a previous dataset does not throw mid-transition. */
export function emphasisForHighlight(layout: SankeyChartLayout, highlight: SankeyHighlight): SankeyEmphasis {
    const nodes = new Set<SankeyNodeDatum>()
    const links = new Set<SankeyLinkDatum>()
    for (const node of layout.nodes) {
        if (highlight.nodeIds.has(node.id)) {
            nodes.add(node)
        }
    }
    for (const index of highlight.linkIndices) {
        const link = layout.links[index]
        if (link) {
            links.add(link)
        }
    }
    return { nodes, links }
}

function paintEmphasis(
    ctx: CanvasRenderingContext2D,
    layout: SankeyChartLayout,
    emphasis: SankeyEmphasis,
    options: DrawSankeyOptions & { dimTarget: string; progress: number }
): void {
    const dim = options.progress * HOVER_DIM_AMOUNT
    // The dim fill must be opaque: a translucent repaint composites over the full-color static
    // layer and does not dim at all.
    for (const link of layout.links) {
        if (!emphasis.links.has(link)) {
            // Mix from the color the link rests at, then paint opaque, so the dim replaces the static
            // ribbon instead of compositing a second translucent pass over it.
            const resting = mixColors(options.dimTarget, link.color, options.linkOpacity)
            strokeLink(ctx, link, mixColors(resting, options.dimTarget, dim), 1)
        }
    }
    for (const node of layout.nodes) {
        if (!emphasis.nodes.has(node)) {
            fillNode(ctx, node, mixColors(node.color, options.dimTarget, dim))
        }
    }
    const activeOpacity = options.linkOpacity + (HOVER_LINK_OPACITY - options.linkOpacity) * options.progress
    for (const link of emphasis.links) {
        strokeLink(ctx, link, link.color, activeOpacity)
    }
    for (const node of emphasis.nodes) {
        const color =
            node === emphasis.focus
                ? mixColors(node.color, HOVER_HIGHLIGHT_TARGET, HOVER_HIGHLIGHT_AMOUNT * options.progress)
                : node.color
        fillNode(ctx, node, color)
    }
}

/** Static layer: every ribbon under every node, in input order. With `emphasis`, the graph is
 *  painted already dimmed around that set, which is how a controlled highlight shows. */
export function drawSankey(
    ctx: CanvasRenderingContext2D,
    layout: SankeyChartLayout,
    options: DrawSankeyOptions & { emphasis?: SankeyEmphasis | null; backgroundColor?: string }
): void {
    if (options.emphasis) {
        paintEmphasis(ctx, layout, options.emphasis, {
            linkOpacity: options.linkOpacity,
            dimTarget: options.backgroundColor || HOVER_DIM_TARGET_FALLBACK,
            progress: 1,
        })
        return
    }
    for (const link of layout.links) {
        strokeLink(ctx, link, link.color, options.linkOpacity)
    }
    for (const node of layout.nodes) {
        fillNode(ctx, node, node.color)
    }
}

/** Hover layer: dims the graph toward the background, then repaints the hovered node or ribbon
 *  and everything connected to it at full strength. Returns false when nothing is hovered. */
export function drawSankeyHover(
    ctx: CanvasRenderingContext2D,
    layout: SankeyChartLayout,
    hit: SankeyHit | null,
    options: DrawSankeyOptions & { backgroundColor?: string; progress: number }
): boolean {
    const emphasis = emphasisForHit(layout, hit)
    if (!emphasis) {
        return false
    }
    paintEmphasis(ctx, layout, emphasis, {
        linkOpacity: options.linkOpacity,
        dimTarget: options.backgroundColor || HOVER_DIM_TARGET_FALLBACK,
        progress: options.progress,
    })
    return true
}
