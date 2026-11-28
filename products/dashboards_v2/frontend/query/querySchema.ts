import { z } from 'zod'

import type { QuerySchema } from '~/queries/schema/schema-general'

/**
 * The query a data panel runs, in one of the languages the host's runner understands:
 * - `hogql`: a HogQL `SELECT`.
 * - `query`: any query node `/query` runs, such as a `TrendsQuery`, a `MetricsQuery` or a `TraceSpansQuery`.
 * - `promql` and `logql`: an expression, run as a range query over the chart's time range.
 * These are the query batch endpoint's language names, so a saved board runs on any client.
 */
export type PanelQuery =
    | { language: 'hogql'; query: string }
    | { language: 'query'; query: QuerySchema }
    | { language: 'promql'; query: string }
    | { language: 'logql'; query: string }

// The query batch endpoint's limit. A longer value fails the whole batch, and with it every other tile's query.
const MAX_QUERY_TEXT = 200_000

// Only a node's kind is checked here. The node schemas are large, and PostHog checks the rest when it runs the query.
export const panelQuerySchema = z.union([
    z.strictObject({ language: z.literal('hogql'), query: z.string().regex(/\S/).max(MAX_QUERY_TEXT) }),
    z.strictObject({ language: z.literal('query'), query: z.looseObject({ kind: z.string().min(1) }) }),
    z.strictObject({ language: z.literal('promql'), query: z.string().regex(/\S/).max(MAX_QUERY_TEXT) }),
    z.strictObject({ language: z.literal('logql'), query: z.string().regex(/\S/).max(MAX_QUERY_TEXT) }),
]) as unknown as z.ZodType<PanelQuery>
