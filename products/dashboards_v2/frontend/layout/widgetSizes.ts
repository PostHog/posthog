import { type ContentWidget, GRID, type Widget, showsPart } from './dashboardTypes'

interface WidgetSize {
    w: number
    h: number
    minW: number
    minH: number
}

/** One entry per widget type. A team adding a widget type adds its sizes here and its component in `WidgetView`. */
const WIDGET_SIZES: Record<Widget['type'], WidgetSize> = {
    stat: { w: 6, h: 3, minW: 3, minH: 2 },
    line: { w: 12, h: 8, minW: 4, minH: 4 },
    bar: { w: 12, h: 8, minW: 4, minH: 4 },
    markdown: { w: 8, h: 4, minW: 3, minH: 2 },
    // A section's height follows its tiles, so `h` and `minH` here only cover a new, empty one.
    section: { w: 24, h: 3, minW: 4, minH: 1 },
}

export function widgetSize(widget: Widget): WidgetSize {
    return WIDGET_SIZES[widget.type]
}

/** Heights of the fixed parts of a content tile's quill `sm` card. Update them if the card's spacing changes. */
const CARD_PX = { frame: 14, partGap: 12, header: 24, description: 16, footer: 46 }

/** The least room a widget's body needs before its content clips. */
const MIN_BODY_PX: Record<ContentWidget['type'], number> = { stat: 20, line: 80, bar: 80, markdown: 20 }

/**
 * The fewest rows a content tile can have without clipping, at this tile spacing. A smaller gap makes each row span
 * less height, so a tile with a header and footer can need one more row on a tight dashboard than on a standard one.
 */
export function minRows(widget: Widget, gapPx: number): number {
    if (widget.type === 'section') {
        return widgetSize(widget).minH
    }
    let px = CARD_PX.frame + MIN_BODY_PX[widget.type]
    if (widget.title && showsPart(widget, 'header')) {
        px += CARD_PX.header + CARD_PX.partGap
        if (widget.description && showsPart(widget, 'description')) {
            px += CARD_PX.description
        }
    }
    if (widget.footer?.length && showsPart(widget, 'footer')) {
        px += CARD_PX.footer + CARD_PX.partGap
    }
    return Math.max(widgetSize(widget).minH, Math.ceil((px + gapPx) / (GRID.rowPx + gapPx)))
}
