import { ELLIPSIS, truncateToWidth } from '../../utils/text-measure'
import { type FlameShades, type FlameInk, MARK_GONE, MARK_NEW } from './flame-colors'
import { type FlameCell, type FlameRowGeometry, type FlameTree, MIN_NODE_PX, rowTop } from './flame-layout'

const MONOSPACE_FONT_SIZE = 11
const LABEL_FONT = `${MONOSPACE_FONT_SIZE}px ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace`
const LABEL_PADDING = 5
const MIN_LABEL_WIDTH = LABEL_PADDING * 2 + 12
const MIN_GAP_WIDTH = 4
const GONE_ALPHA = 0.45
const NEW_OUTLINE_ALPHA = 0.7
const HOVER_LINE_WIDTH = 2

const PRINTABLE_ASCII = /^[\x20-\x7e]*$/
const MAX_CACHED_WIDTHS = 4096

/** ASCII labels are cut by arithmetic on one measured monospace character width, so most labels skip `measureText`. */
export interface LabelFitter {
    font: string
    fit: (ctx: CanvasRenderingContext2D, text: string, available: number) => string
}

export function createLabelFitter(): LabelFitter {
    let charWidth = 0
    const widths = new Map<string, number>()
    const fitted = new Map<string, { available: number; label: string }>()

    const measure = (ctx: CanvasRenderingContext2D, text: string): number => {
        let width = widths.get(text)
        if (width === undefined) {
            if (widths.size >= MAX_CACHED_WIDTHS) {
                widths.clear()
            }
            width = ctx.measureText(text).width
            widths.set(text, width)
        }
        return width
    }

    const fit = (ctx: CanvasRenderingContext2D, text: string, available: number): string => {
        if (available <= 0 || !text) {
            return ''
        }
        if (PRINTABLE_ASCII.test(text)) {
            if (charWidth === 0) {
                charWidth = ctx.measureText('0123456789').width / 10 || MONOSPACE_FONT_SIZE * 0.6
            }
            const maxChars = Math.floor(available / charWidth)
            if (text.length <= maxChars) {
                return text
            }
            return maxChars >= 2 ? `${text.slice(0, maxChars - 1).trimEnd()}${ELLIPSIS}` : ''
        }
        if (measure(ctx, text) <= available) {
            return text
        }
        const hit = fitted.get(text)
        if (hit?.available === available) {
            return hit.label
        }
        const truncated = truncateToWidth(text, available, LABEL_FONT)
        const label = truncated === ELLIPSIS ? '' : truncated
        if (fitted.size >= MAX_CACHED_WIDTHS) {
            fitted.clear()
        }
        fitted.set(text, { available, label })
        return label
    }

    return { font: LABEL_FONT, fit }
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
    matches: Uint8Array | null
    containsMatch: Uint8Array | null
    ancestors: ReadonlySet<number>
    scrollTop: number
    width: number
    pixelRatio: number
}

export interface CellRect {
    x: number
    y: number
    width: number
    height: number
}

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
    ctx.font = fitter.font
    ctx.textBaseline = 'middle'
    ctx.textAlign = 'left'

    for (const cell of cells) {
        const rect = cellRect(cell, geometry, input.scrollTop, input.width, input.pixelRatio)
        const isBundle = cell.kind === 'bundle'
        const mark = isBundle ? 0 : marks[cell.index]
        let fill = isBundle ? ink.neutral : fills[cell.index]
        let textColor: string | null = null
        if (matches && containsMatch) {
            // A narrow node's children aren't drawn, so it stands in for any match under it.
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
