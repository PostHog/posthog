import type { Widget } from './dashboardTypes'

interface WidgetSize {
    w: number
    h: number
    minW: number
    minH: number
    /** A chart sized for a wide screen would fill a phone, so a stacked chart stays between these heights. */
    stackedRows?: { min: number; max: number }
}

/**
 * One entry per widget type. A team adding a widget type adds its sizes here, its component in `WidgetView` and, for a
 * footer, its content in `WidgetFooter`.
 */
const WIDGET_SIZES: Record<Widget['type'], WidgetSize> = {
    stat: { w: 6, h: 3, minW: 3, minH: 2 },
    line: { w: 12, h: 8, minW: 4, minH: 4, stackedRows: { min: 5, max: 8 } },
    bar: { w: 12, h: 8, minW: 4, minH: 4, stackedRows: { min: 5, max: 8 } },
    markdown: { w: 8, h: 4, minW: 3, minH: 2 },
    // A section's height follows its tiles, so `h` and `minH` here only cover a new, empty one.
    section: { w: 24, h: 3, minW: 4, minH: 1 },
}

export function widgetSize(widget: Widget): WidgetSize {
    return WIDGET_SIZES[widget.type]
}
