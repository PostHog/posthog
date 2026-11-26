import { z } from 'zod'

import {
    type MetricsQuery,
    NodeKind,
    type QuerySchema,
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
 * The query a data panel runs, in one of the languages the host's runner understands:
 * - `hogql`: a HogQL `SELECT`.
 * - `metrics`: a `MetricsQuery` node, as the metrics product builds it.
 * - `traces`: a `TraceSpansQuery` or `TraceSpansAggregationQuery` node, as tracing and APM build them.
 * - `insight`: any query node `/query` runs, such as a `TrendsQuery`, for teams that already build their own nodes.
 * - `promql` and `logql`: an expression, run as a range query over the chart's time range.
 */
export type PanelQuery =
    | { language: 'hogql'; query: string }
    | { language: 'metrics'; query: MetricsQuery }
    | { language: 'traces'; query: TraceSpansQuery | TraceSpansAggregationQuery }
    | { language: 'insight'; query: QuerySchema }
    | { language: 'promql'; query: string }
    | { language: 'logql'; query: string }

// The query batch endpoint's limits. A longer value fails the whole batch, and with it every other tile's query.
const MAX_QUERY_TEXT = 200_000
const MAX_TIME_END = 100

// Only a node's kind is checked here. The node schemas are large, and PostHog checks the rest when it runs the query.
export const panelQuerySchema = z.union([
    z.strictObject({ language: z.literal('hogql'), query: z.string().regex(/\S/).max(MAX_QUERY_TEXT) }),
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
    z.strictObject({ language: z.literal('insight'), query: z.looseObject({ kind: z.string().min(1) }) }),
    z.strictObject({ language: z.literal('promql'), query: z.string().regex(/\S/).max(MAX_QUERY_TEXT) }),
    z.strictObject({ language: z.literal('logql'), query: z.string().regex(/\S/).max(MAX_QUERY_TEXT) }),
]) as unknown as z.ZodType<PanelQuery>

/**
 * The time range a query runs over. Each end is an expression such as `now-7d` or `now`, or an ISO 8601 time. Keep
 * relative ends relative, because the backend then caches the result under the same key on every reload.
 */
export const timeRangeSchema = z.strictObject({
    from: z.string().min(1).max(MAX_TIME_END),
    to: z.string().min(1).max(MAX_TIME_END),
})

export const tilePlaceSchema = z.strictObject({
    x: z.int().nonnegative(),
    y: z.int().nonnegative(),
    w: z.int().positive(),
    h: z.int().positive(),
})

/** Which parts of a content tile show. A part that is missing shows. */
export const contentPanelPartsSchema = z.strictObject({
    header: z.boolean().optional(),
    footer: z.boolean().optional(),
})

/** How a tile looks. A setting that is missing is on. A section has no background to change. */
export const tileAppearanceSchema = z.strictObject({
    background: z.boolean().optional(),
    border: z.boolean().optional(),
    /** Any CSS color. The tile mixes it into its background as a tint. */
    backgroundColor: z.string().min(1).optional(),
})

/**
 * The fields every content tile has. Everything specific to the panel type, such as a chart's query, sits in
 * `config`, which is checked against the type's own `configSchema`.
 */
export const contentPanelSchema = z.strictObject({
    /** Names the panel type that renders it. The host supplies the types, so this is open, except for `section`. */
    type: z.string().refine((type) => type !== 'section', 'A section needs a title and tiles'),
    title: z.string().optional(),
    description: z.string().optional(),
    /** When the panel's data was last computed, as an ISO timestamp. */
    refreshedAt: z.iso.datetime({ offset: true }).optional(),
    parts: contentPanelPartsSchema.optional(),
    appearance: tileAppearanceSchema.optional(),
    config: z.unknown(),
    /** Set once the panel shows on more than one tile. Its content is then saved once, in the document's `panels`. */
    ref: z.string().min(1).optional(),
})

/** A panel shown on several tiles. Each tile chooses its own parts and appearance. */
export const sharedPanelSchema = contentPanelSchema.omit({ parts: true, appearance: true, ref: true })

/** A tile's panel in a saved document when the panel is shared: its key in `panels`, and how this tile shows it. */
export const panelRefSchema = z.strictObject({
    ref: z.string().min(1),
    parts: contentPanelPartsSchema.optional(),
    appearance: tileAppearanceSchema.optional(),
})

/**
 * A grid inside a tile. Its cells line up with the cells of the grid it sits in: one row for the header, then its
 * own tiles. Its height always fits its tiles, so `place.h` of a section tile is worked out, never chosen.
 */
export const sectionPanelSchema = z.strictObject({
    type: z.literal('section'),
    title: z.string(),
    collapsed: z.boolean().optional(),
    appearance: tileAppearanceSchema.optional(),
    /** The height a person resized the section to, in rows. It still grows past this when its tiles need more. */
    minRows: z.int().positive().optional(),
    get tiles(): z.ZodArray<typeof tileSchema> {
        return z.array(tileSchema)
    },
})

export const tileSchema = z.strictObject({
    id: z.string().min(1),
    place: tilePlaceSchema,
    get panel(): z.ZodUnion<[typeof sectionPanelSchema, typeof contentPanelSchema]> {
        return z.union([sectionPanelSchema, contentPanelSchema])
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
    /** A path in PostHog, such as `/dashboard-v2?tab=errors`, or an http(s) URL. Anything else could run script. */
    href: z
        .string()
        .refine(
            (href) => /^\/(?![/\\])/.test(href) || /^https?:\/\//i.test(href),
            'A link tab goes to a PostHog path or an http(s) URL'
        ),
})

export const dashboardTabSchema = z.union([gridTabSchema, linkTabSchema])

export const ONE_GRID_TAB = 'A dashboard needs at least one tab with tiles'

export const dashboardSchema = z.strictObject({
    version: z.literal(2),
    title: z.string(),
    description: z.string().optional(),
    /** The viewer's access to this dashboard, as v1 dashboards carry it. Missing means the project-wide level. */
    user_access_level: z.enum(AccessControlLevel).optional(),
    /** The time range of every panel that does not set its own. Missing means `DEFAULT_TIME_RANGE`. */
    time: timeRangeSchema.optional(),
    tabs: z.array(dashboardTabSchema).refine((tabs) => tabs.some((tab) => 'tiles' in tab), ONE_GRID_TAB),
})

/** A tile's own panel in a saved document. A shared panel is saved once in `panels`, so its tiles carry no `ref` here. */
export const documentContentPanelSchema = contentPanelSchema.omit({ ref: true })

const documentSectionSchema = sectionPanelSchema.extend({
    get tiles(): z.ZodArray<typeof documentTileSchema> {
        return z.array(documentTileSchema)
    },
})

const documentTileSchema = tileSchema.extend({
    get panel(): z.ZodUnion<[typeof documentSectionSchema, typeof documentContentPanelSchema, typeof panelRefSchema]> {
        return z.union([documentSectionSchema, documentContentPanelSchema, panelRefSchema])
    },
})

/**
 * The dashboard as it is saved. It is `dashboardSchema` with shared panels stored once: a tile shows one through a
 * `panelRefSchema`, and `loadDashboard` puts each back on its tiles.
 */
export const dashboardDocumentSchema = dashboardSchema.extend({
    panels: z.record(z.string(), sharedPanelSchema).optional(),
    tabs: z
        .array(z.union([gridTabSchema.extend({ tiles: z.array(documentTileSchema) }), linkTabSchema]))
        .refine((tabs) => tabs.some((tab) => 'tiles' in tab), ONE_GRID_TAB),
})
