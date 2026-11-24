import { z } from 'zod'

import { type WidgetQuery, timeRangeSchema, widgetQuerySchema } from '../../dashboard/dashboardSchema'
import type { TimeRange } from '../../dashboard/dashboardTypes'
import { UNKNOWN_WIDGET_SIZE, type WidgetSpec } from '../widgetSpec'
import type { VizSpec } from './vizTypes'

export interface ChartConfig {
    query: WidgetQuery
    /** How the result is drawn. Changing it never changes the data. */
    viz: { type: string; options?: unknown }
    /** Overrides the time range around the chart, such as the dashboard's. */
    time?: TimeRange
}

/**
 * A widget that runs one query and draws it as one of `vizTypes`. The add menu offers one "Chart" item, which starts
 * as a line chart, and the tile's "Chart type" menu switches it to any other kind.
 */
export function chartSpec(vizTypes: VizSpec[]): WidgetSpec<ChartConfig> {
    const firstType = vizTypes.find((viz) => viz.type === 'line')?.type ?? vizTypes[0]?.type ?? 'line'
    const vizSchemas = vizTypes.map((viz) =>
        // Missing options are read as `{}`, so they are checked as `{}` too.
        z.strictObject({
            type: z.literal(viz.type),
            options: z.preprocess((options) => options ?? {}, viz.optionsSchema),
        })
    )
    return {
        type: 'chart',
        addMenuItems: [
            {
                label: 'Chart',
                // TODO(2026-11-23): Replace this hardcoded query with one the person picks when they add the tile.
                // The query is temporary. It gives the add menu a widget to insert before a query picker exists.
                create: () => ({
                    type: 'chart',
                    title: 'New chart',
                    config: {
                        query: { language: 'hogql', query: 'select count() from events' },
                        viz: { type: firstType },
                    },
                }),
            },
        ],
        size: UNKNOWN_WIDGET_SIZE,
        sizeFor: (widget) => vizTypes.find((viz) => viz.type === widget.config?.viz?.type)?.size ?? UNKNOWN_WIDGET_SIZE,
        configSchema: z.strictObject({
            query: widgetQuerySchema,
            viz: vizSchemas.length > 0 ? z.union(vizSchemas) : z.never(),
            time: timeRangeSchema.optional(),
        }),
        refreshes: true,
    }
}
