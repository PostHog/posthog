import { ELLIPSIS } from '../../utils/text-measure'
import { type FlameShades, type FlameInk, MARK_GONE, MARK_NEW } from './flame-colors'
import { type FlameCell, type FlameRowGeometry, type FlameTree, MIN_NODE_PX, rowTop } from './flame-layout'

export const LABEL_FONT_SIZE = 11
export const LABEL_FONT = `${LABEL_FONT_SIZE}px ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace`
const LABEL_PADDING = 5
/** Below this a cell is too narrow for even one character and an ellipsis. */
const MIN_LABEL_WIDTH = LABEL_PADDING * 2 + 12
/** Cells at least this wide leave a 1px gap on the right, so neighbors read as separate. */
const MIN_GAP_WIDTH = 4
const GONE_ALPHA = 0.45
const NEW_OUTLINE_ALPHA = 0.7
const HOVER_LINE_WIDTH = 2

const PRINTABLE_ASCII = /^[\x20-\x7e]*$/

/**
 * Truncates labels to a width. The label font is monospace, so an ASCII label is cut by
 * arithmetic on one measured character width, without a `measureText` call per label. Other
 * labels (wide CJK glyphs, emoji) fall back to measuring, with full widths cached.
 */
export class LabelFitter {
    private charWidth = 0
    private readonly widths = new Map<string, number>()

    fit(ctx: CanvasRenderingContext2D, text: string, available: number): string {
        if (available <= 0 || !text) {
            return ''
        }
        if (PRINTABLE_ASCII.test(text)) {
            if (this.charWidth === 0) {
                this.charWidth = ctx.measureText('0123456789').width / 10 || LABEL_FONT_SIZE * 0.6
            }
            const maxChars = Math.floor(available / this.charWidth)
            if (text.length <= maxChars) {
                return text
            }
            return maxChars >= 2 ? `${text.slice(0, maxChars - 1).trimEnd()}${ELLIPSIS}` : ''
        }
        if (this.measure(ctx, text) <= available) {
            return text
        }
        let lo = 0
        let hi = text.length
        while (lo < hi) {
            const mid = Math.ceil((lo + hi) / 2)
            if (ctx.measureText(`${text.slice(0, mid)}${ELLIPSIS}`).width <= available) {
                lo = mid
            } else {
                hi = mid - 1
            }
        }
        return lo > 0 ? `${text.slice(0, lo).trimEnd()}${ELLIPSIS}` : ''
    }

    private measure(ctx: CanvasRenderingContext2D, text: string): number {
        let width = this.widths.get(text)
        if (width === undefined) {
            width = ctx.measureText(text).width
            this.widths.set(text, width)
        }
        return width
    }
}

export interface FlameDrawInput {
    tree: FlameTree<unknown>
    cells: readonly FlameCell[]
    fills: readonly string[]
    marks: Uint8Array
    ink: FlameInk
    shades: FlameShades
    fitter: LabelFitter
    geometry: FlameRowGeometry
    /** Search matches, or null without a search. */
    matches: Uint8Array | null
    containsMatch: Uint8Array | null
    /** Ancestors of the focused node, drawn faded because they span the whole width. */
    ancestors: ReadonlySet<number>
    scrollTop: number
    width: number
    /** Device pixels per CSS pixel, for snapping edges. */
    pixelRatio: number
}

export interface CellRect {
    x: number
    y: number
    width: number
    height: number
}

/** The drawn rectangle of a cell, snapped to device pixels and clipped to the plot width. */
export function cellRect(
    cell: FlameCell,
    geometry: FlameRowGeometry,
    scrollTop: number,
    width: number,
    pixelRatio: number
): CellRect {
    const snap = (v: number): number => Math.round(v * pixelRatio) / pixelRatio
    const left = snap(Math.max(cell.x0, -1))
    const right = snap(Math.min(cell.x1, width + 1))
    const full = right - left
    return {
        x: left,
        y: rowTop(cell.depth, geometry) - scrollTop,
        width: Math.max(1 / pixelRatio, full >= MIN_GAP_WIDTH ? full - 1 : full),
        height: geometry.rowHeight - 1,
    }
}

function bundleCount(cell: FlameCell): number {
    return cell.last - cell.index + 1
}

function bundleHasMatch(cell: FlameCell, containsMatch: Uint8Array): boolean {
    for (let i = cell.index; i <= cell.last; i++) {
        if (containsMatch[i]) {
            return true
        }
    }
    return false
}

export function drawFlame(ctx: CanvasRenderingContext2D, input: FlameDrawInput): void {
    const { tree, cells, fills, marks, ink, shades, fitter, geometry, matches, containsMatch, ancestors } = input
    ctx.font = LABEL_FONT
    ctx.textBaseline = 'middle'
    ctx.textAlign = 'left'

    for (const cell of cells) {
        const rect = cellRect(cell, geometry, input.scrollTop, input.width, input.pixelRatio)
        const isBundle = cell.kind === 'bundle'
        const mark = isBundle ? 0 : marks[cell.index]
        let fill = isBundle ? ink.neutral : fills[cell.index]
        let textColor: string | null = null
        if (matches && containsMatch) {
            // The children of a narrow node are not drawn, so it stands in for any match under it.
            const narrow = cell.x1 - cell.x0 < MIN_NODE_PX
            const hit = isBundle
                ? bundleHasMatch(cell, containsMatch)
                : (narrow ? containsMatch : matches)[cell.index] === 1
            if (!hit) {
                fill = shades.searchMiss
                textColor = shades.searchMissText
            }
        } else if (ancestors.has(cell.index)) {
            fill = shades.ancestorOf(fill)
        }

        ctx.globalAlpha = mark & MARK_GONE ? GONE_ALPHA : 1
        ctx.fillStyle = fill
        ctx.fillRect(rect.x, rect.y, rect.width, rect.height)

        if (mark & MARK_NEW && rect.width >= 4) {
            ctx.globalAlpha = NEW_OUTLINE_ALPHA
            ctx.strokeStyle = ink.ink
            ctx.lineWidth = 1
            ctx.setLineDash([3, 2])
            ctx.strokeRect(rect.x + 0.5, rect.y + 0.5, rect.width - 1, rect.height - 1)
            ctx.setLineDash([])
            ctx.globalAlpha = 1
        }

        // A cell clipped on the left keeps its label in view at the plot edge.
        const textLeft = Math.max(rect.x, 0) + LABEL_PADDING
        const textRight = Math.min(rect.x + rect.width, input.width) - LABEL_PADDING
        if (textRight - textLeft + LABEL_PADDING * 2 < MIN_LABEL_WIDTH) {
            continue
        }
        const name = isBundle ? `+${bundleCount(cell)} more` : String(tree.nodes[cell.index].name ?? '')
        const label = fitter.fit(ctx, name, textRight - textLeft)
        if (label) {
            ctx.fillStyle = textColor ?? shades.textOn(fill)
            ctx.fillText(label, textLeft, rect.y + rect.height / 2 + 0.5)
        }
    }
    ctx.globalAlpha = 1
}

export function drawFlameHover(ctx: CanvasRenderingContext2D, rect: CellRect, ink: FlameInk): void {
    const inset = HOVER_LINE_WIDTH / 2
    ctx.strokeStyle = ink.ink
    ctx.lineWidth = HOVER_LINE_WIDTH
    ctx.strokeRect(
        rect.x + inset,
        rect.y + inset,
        Math.max(0, rect.width - HOVER_LINE_WIDTH),
        Math.max(0, rect.height - HOVER_LINE_WIDTH)
    )
}
