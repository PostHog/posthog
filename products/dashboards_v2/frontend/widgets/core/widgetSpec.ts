import type { z } from 'zod'

import type { ContentWidget, SavedWidget, SizeOf, WidgetSize } from '../../dashboard/document/dashboardTypes'
import { parseOnce } from '../../schema/parseOnce'

/** A way a person can customize a tile in its menu. The menu offers only the ones a widget type allows. */
export type TileCustomization = 'backgroundColor'

/**
 * Everything about a widget type except how it renders. It is plain data with no React, so code outside the browser
 * can load it: the layout functions, `validateDashboard`, and tools that write dashboards as code.
 */
export type WidgetSpec<Config, Type extends string = string> = {
    type: Type
    size: WidgetSize
    /** Overrides `size` for one widget, such as a chart sized by its kind of chart. */
    sizeFor?(widget: ContentWidget<Config>): WidgetSize
    /** The shape of `config` on widgets of this type. Every saved config is checked against it before it is used. */
    configSchema: z.ZodType<Config>
    allowedCustomizations?: TileCustomization[]
}

/**
 * A widget type in a list of mixed types, made by `defineWidgetSpec`. It takes saved widgets and checks each config
 * against the type's `configSchema` before the type's own functions see it.
 */
export type WidgetTypeSpec<Type extends string = string> = {
    type: Type
    size: WidgetSize
    /** The size of one saved widget. A widget whose config does not match the schema gets `size`. */
    sizeOf: SizeOf
    configError(config: SavedWidget['config']): z.ZodError | null
    allowedCustomizations?: TileCustomization[]
}

export function defineWidgetSpec<Config, const Type extends string>(
    spec: WidgetSpec<Config, Type>
): WidgetTypeSpec<Type> {
    const { configSchema, sizeFor } = spec
    return {
        type: spec.type,
        size: spec.size,
        sizeOf: (widget) => {
            const config = parseOnce(configSchema, widget.config)
            return sizeFor && config.success ? sizeFor({ ...widget, config: config.data }) : spec.size
        },
        configError: (config) => {
            const result = parseOnce(configSchema, config)
            return result.success ? null : result.error
        },
        allowedCustomizations: spec.allowedCustomizations,
    }
}

/** For a saved widget whose type the host did not pass in, so it still gets a place in the grid. */
export const UNKNOWN_WIDGET_SIZE: WidgetSize = { w: 6, h: 8, minW: 2, minH: 4 }

export function findWidget<T extends { type: string }>(widgets: T[], type: string): T | undefined {
    return widgets.find((widget) => widget.type === type)
}

export function sizeOfWidgets(widgets: WidgetTypeSpec[]): SizeOf {
    return (widget) => findWidget(widgets, widget.type)?.sizeOf(widget) ?? UNKNOWN_WIDGET_SIZE
}
