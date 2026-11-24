import { z } from 'zod'

import {
    type MetricsQuery,
    NodeKind,
    type TraceSpansAggregationQuery,
    type TraceSpansQuery,
} from '~/queries/schema/schema-general'
import { AccessControlLevel } from '~/types'

/**
 * The dashboard document as JSON. These schemas are the only definition of its shape: the types in `dashboardTypes.ts`
 * are inferred from them, and `validateDashboard` checks documents against them. Objects are strict, so a misspelled
 * field in a hand-written dashboard is reported instead of ignored.
 */

/**
 * The query a data widget runs, in one of the languages the host's runner understands:
 * - `hogql`: a HogQL `SELECT`.
 * - `metrics`: a `MetricsQuery` node, as the metrics product builds it.
 * - `traces`: a `TraceSpansQuery` or `TraceSpansAggregationQuery` node, as tracing and APM build them.
 */
export type WidgetQuery =
    | { language: 'hogql'; query: string }
    | { language: 'metrics'; query: MetricsQuery }
    | { language: 'traces'; query: TraceSpansQuery | TraceSpansAggregationQuery }

// Only a node's kind is checked here. The node schemas are large, and PostHog checks the rest when it runs the query.
export const widgetQuerySchema = z.union([
    z.strictObject({ language: z.literal('hogql'), query: z.string().min(1) }),
    z.strictObject({
        language: z.literal('metrics'),
        query: z.looseObject({ kind: z.literal(NodeKind.MetricsQuery) }),
    }),
    z.strictObject({
        language: z.literal('traces'),
        query: z.looseObject({
            kind: z.enum([NodeKind.TraceSpansQuery, NodeKind.TraceSpansAggregationQuery]),
        }),
    }),
]) as unknown as z.ZodType<WidgetQuery>

export const tilePlaceSchema = z.strictObject({
    x: z.int().nonnegative(),
    y: z.int().nonnegative(),
    w: z.int().positive(),
    h: z.int().positive(),
})

/** Which parts of a content tile show. A part that is missing shows. */
export const contentWidgetPartsSchema = z.strictObject({
    header: z.boolean().optional(),
    description: z.boolean().optional(),
    footer: z.boolean().optional(),
})

/**
 * The fields every content tile has. Everything specific to the widget type, such as a chart's query, sits in
 * `config`, which is checked against the type's own `configSchema`.
 */
export const contentWidgetSchema = z.strictObject({
    /** Names the widget type that renders it. The host supplies the types, so this is open. */
    type: z.string(),
    title: z.string().optional(),
    description: z.string().optional(),
    /** When the widget's data was last computed, as an ISO timestamp. */
    refreshedAt: z.iso.datetime({ offset: true }).optional(),
    parts: contentWidgetPartsSchema.optional(),
    config: z.unknown(),
})

/**
 * A grid inside a tile. Its cells line up with the cells of the grid it sits in: one row for the header, then its
 * own tiles. Its height always fits its tiles, so `place.h` of a section tile is worked out, never chosen.
 */
export const sectionWidgetSchema = z.strictObject({
    type: z.literal('section'),
    title: z.string(),
    collapsed: z.boolean().optional(),
    /** The height a person resized the section to, in rows. It still grows past this when its tiles need more. */
    minRows: z.int().positive().optional(),
    get tiles(): z.ZodArray<typeof tileSchema> {
        return z.array(tileSchema)
    },
})

export const tileSchema = z.strictObject({
    id: z.string().min(1),
    place: tilePlaceSchema,
    get widget(): z.ZodUnion<[typeof sectionWidgetSchema, typeof contentWidgetSchema]> {
        return z.union([sectionWidgetSchema, contentWidgetSchema])
    },
})

/** A tab that holds a grid of tiles. */
export const gridTabSchema = z.strictObject({
    id: z.string().min(1),
    title: z.string(),
    tiles: z.array(tileSchema),
})

/** A tab that goes somewhere else when picked, such as another dashboard or another page, and holds no tiles. */
export const linkTabSchema = z.strictObject({
    id: z.string().min(1),
    title: z.string(),
    /** A path in PostHog, such as `/dashboard-v2?tab=errors`, or a full URL. */
    href: z.string().min(1),
})

export const dashboardTabSchema = z.union([gridTabSchema, linkTabSchema])

export const ONE_GRID_TAB = 'A dashboard needs at least one tab with tiles'

export const dashboardSchema = z.strictObject({
    version: z.literal(2),
    title: z.string(),
    /** The viewer's access to this dashboard, as v1 dashboards carry it. Missing means the project-wide level. */
    user_access_level: z.enum(AccessControlLevel).optional(),
    tabs: z.array(dashboardTabSchema).refine((tabs) => tabs.some((tab) => 'tiles' in tab), ONE_GRID_TAB),
})
