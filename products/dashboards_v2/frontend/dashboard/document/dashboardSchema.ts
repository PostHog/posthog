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
 * are inferred from them, and `validateDashboard` checks documents against them. Objects accept fields they don't
 * know, as the boards API does, so a board a newer client saved still opens. Parsing strips those fields, so load the
 * document as given once it is valid, and the fields survive the next save. `validateDashboard` reports them as
 * warnings, so a misspelled field in a hand-written dashboard still shows.
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

export const RELATIVE_TIME = /^now-(\d+)([smhdwMy])$/

const timePointSchema = z
    .string()
    .max(MAX_TIME_END)
    .refine(
        (point) => point === 'now' || RELATIVE_TIME.test(point) || !Number.isNaN(Date.parse(point)),
        'Use now, now-<amount><s|m|h|d|w|M|y>, or an ISO 8601 time'
    )

/**
 * The time range a query runs over. Each end is an expression such as `now-7d` or `now`, or an ISO 8601 time. Keep
 * relative ends relative, because the backend then caches the result under the same key on every reload.
 */
export const timeRangeSchema = z.object({ from: timePointSchema, to: timePointSchema })

export const tilePlaceSchema = z.object({
    x: z.int().nonnegative(),
    y: z.int().nonnegative(),
    w: z.int().positive(),
    h: z.int().positive(),
})

/** Which parts of a content tile show. A part that is missing shows. */
export const contentPanelPartsSchema = z.object({
    header: z.boolean().optional(),
    footer: z.boolean().optional(),
})

/** How a tile looks. A setting that is missing is on. A section has no background to change. */
export const tileAppearanceSchema = z.object({
    border: z.boolean().optional(),
    /** Any CSS color. The tile mixes it into its background as a tint, and `transparent` removes the background. */
    backgroundColor: z.string().min(1).optional(),
})

/**
 * The fields every content tile has. Everything specific to the panel type, such as a chart's query, sits in
 * `config`, which is checked against the type's own `configSchema`.
 */
export const contentPanelSchema = z.object({
    /** Names the panel type that renders it. The host supplies the types, so this is open, except for `section`. */
    type: z.string().refine((type) => type !== 'section', 'A section needs a title and tiles'),
    title: z.string().optional(),
    description: z.string().optional(),
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
export const panelRefSchema = z.object({
    ref: z.string().min(1),
    parts: contentPanelPartsSchema.optional(),
    appearance: tileAppearanceSchema.optional(),
})

/**
 * A grid inside a tile. Its cells line up with the cells of the grid it sits in: one row for the header, then its
 * own tiles. Its height always fits its tiles, so `place.h` of a section tile is worked out, never chosen.
 */
export const sectionPanelSchema = z.object({
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

export const tileSchema = z.object({
    id: z.string().min(1),
    place: tilePlaceSchema,
    get panel(): z.ZodUnion<[typeof sectionPanelSchema, typeof contentPanelSchema]> {
        return z.union([sectionPanelSchema, contentPanelSchema])
    },
})

export const gridTabSchema = z.object({
    id: z.string().min(1),
    title: z.string(),
    tiles: z.array(tileSchema),
})

/** A tab that goes somewhere else when picked, such as another dashboard or another page, and holds no tiles. */
export const linkTabSchema = z.object({
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

/**
 * A filter a person added to the dashboard. `type` names a kind of filter the host supplies, and `config` is that
 * kind's own settings, such as which property it filters on. The value picked is not saved: each viewer picks their own.
 */
export const dashboardFilterSchema = z.object({
    id: z.string().min(1),
    type: z.string().min(1),
    label: z.string().optional(),
    config: z.unknown(),
})

export const ONE_GRID_TAB = 'A dashboard needs at least one tab with tiles'

export const DASHBOARD_SCHEMA_VERSION = 2 as const

export const dashboardSchema = z.object({
    version: z.literal(DASHBOARD_SCHEMA_VERSION, {
        error: (issue) =>
            typeof issue.input === 'number' && issue.input > DASHBOARD_SCHEMA_VERSION
                ? 'This dashboard was saved by a newer version of PostHog. Refresh the page to open it.'
                : `A dashboards v2 document has version ${DASHBOARD_SCHEMA_VERSION}`,
    }),
    title: z.string(),
    description: z.string().optional(),
    /** Copied out of the document by the boards API, so a list of boards can show and filter them. */
    tags: z.array(z.string()).optional(),
    folder: z.string().optional(),
    /** The viewer's access to this dashboard, as v1 dashboards carry it. Missing means the project-wide level. */
    user_access_level: z.enum(AccessControlLevel).optional(),
    /** The time range of every panel that does not set its own. Missing means each panel keeps its own. */
    time: timeRangeSchema.optional(),
    /** Whether viewers see a filter bar. Missing means no, so a dashboard shows filters only once an editor allows them. */
    allowFilters: z.boolean().optional(),
    filters: z.array(dashboardFilterSchema).optional(),
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
