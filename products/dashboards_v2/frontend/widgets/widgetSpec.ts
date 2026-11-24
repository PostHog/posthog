import type { z } from 'zod'

import type { ContentWidget, SizeOf, WidgetSize } from '../dashboard/dashboardTypes'

/** One entry in the add menu. A widget type can offer several, such as a chart type offering each kind of chart. */
export interface AddMenuItem<Config = unknown> {
    label: string
    /** Builds the new widget the add menu inserts. */
    create: () => ContentWidget<Config>
}

/**
 * Everything about a widget type except how it renders. It is plain data with no React, so code outside the browser
 * can load it: the layout functions, `validateDashboard`, and tools that write dashboards as code.
 */
export interface WidgetSpec<Config = unknown> {
    /** Matches `ContentWidget.type` on the widgets it describes. */
    type: string
    addMenuItems: AddMenuItem<Config>[]
    size: WidgetSize
    /** Overrides `size` for one widget, such as a chart sized by its kind of chart. */
    sizeFor?(widget: ContentWidget<Config>): WidgetSize
    /** The shape of `config` on widgets of this type. `validateDashboard` checks each widget's config against it. */
    configSchema: z.ZodType<Config>
    /** Its widgets show data that refreshes, so their tiles can have a footer with the last refresh time. */
    refreshes?: boolean
}

/** For a saved widget whose type the host did not pass in, so it still gets a place in the grid. */
export const UNKNOWN_WIDGET_SIZE: WidgetSize = { w: 6, h: 8, minW: 2, minH: 4 }

export function findWidget<T extends WidgetSpec>(widgets: T[], type: string): T | undefined {
    return widgets.find((widget) => widget.type === type)
}

export function sizeOfWidgets(widgets: WidgetSpec[]): SizeOf {
    return (widget) => {
        const spec = findWidget(widgets, widget.type)
        if (!spec) {
            return UNKNOWN_WIDGET_SIZE
        }
        return spec.sizeFor?.(widget) ?? spec.size
    }
}
