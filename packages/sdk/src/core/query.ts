// Handwritten runtime for the query wrapper methods on `client.query`. Ported
// from the MCP server's query endpoint helpers (`services/mcp/src/api/client.ts`
// `query()` section and `services/mcp/src/tools/query-wrapper-factory.ts`),
// keeping the query-construction semantics and dropping the MCP-only response
// shaping (`formatted_results` override, `_posthogUrl` enrichment, column/link
// post-processing) — SDK methods return the raw `/query/` endpoint response.

import { type RequestOptions } from './config'
import { Resource } from './resource'

/**
 * Loose fallback response shape, used as the default for the generic
 * `run()` escape hatch. The generated wrapper methods supply precise response
 * types derived from `frontend/src/queries/schema.json`
 * (see `src/generated/query-responses.ts`).
 */
export interface QueryResponse {
    results?: unknown
    [key: string]: unknown
}

/** A query body for the generic escape hatch — any query node the API accepts. */
export interface QueryNode extends Record<string, unknown> {
    kind: string
}

// Bridge assistant-facing schema shape to the query API shape.
// The LLM-facing schemas emit `filterGroup` as a flat array; the API expects a
// nested PropertyGroupFilter.
function normalizeQuery(query: Record<string, unknown>): Record<string, unknown> {
    const normalized = { ...query }
    if (Array.isArray(normalized.filterGroup)) {
        if (normalized.filterGroup.length > 0) {
            normalized.filterGroup = {
                type: 'AND',
                values: [{ type: 'AND', values: normalized.filterGroup }],
            }
        } else {
            delete normalized.filterGroup
        }
    }
    return normalized
}

// The app's retention UI caps the period count at 31; totalIntervals adds the
// acquisition interval → 32. The schema codegen doesn't propagate integer
// min/max, so the bound is enforced here (mirrors the MCP client).
const MAX_RETENTION_INTERVALS = 32

/**
 * Per-source-kind ActorsQuery projection. Mirrors the MCP client's
 * trends/lifecycle/paths/retention/stickiness/funnel actors helpers:
 * - Trends/Paths project `actor` + `event_count`, ordered by event count.
 * - Lifecycle/Stickiness/Funnels project only `actor` (no `matching_events`
 *   unless recordings are requested; funnel ordering is backend-determined).
 * - Retention projects `person` + one column per return interval: prefix =
 *   period (day/week/…), count = custom-bracket count + 1, else totalIntervals.
 */
function actorsProjection(sourceQuery: Record<string, unknown>): { select: string[]; orderBy: string[] } {
    const sourceKind = (sourceQuery.source as Record<string, unknown> | undefined)?.kind
    switch (sourceKind) {
        case 'TrendsQuery':
        case 'PathsQuery':
            return { select: ['actor', 'event_count'], orderBy: ['event_count DESC', 'actor_id DESC'] }
        case 'LifecycleQuery':
        case 'StickinessQuery':
        case 'FunnelsQuery':
            return { select: ['actor'], orderBy: [] }
        case 'RetentionQuery': {
            const filter = ((sourceQuery.source as Record<string, unknown>)?.retentionFilter ?? {}) as Record<
                string,
                unknown
            >
            const period = typeof filter.period === 'string' ? filter.period.toLowerCase() : 'day'
            const brackets = filter.retentionCustomBrackets as number[] | undefined
            const count = brackets?.length ? brackets.length + 1 : (filter.totalIntervals as number) || 7
            if (count > MAX_RETENTION_INTERVALS) {
                throw new Error(
                    `Retention query requests ${count} intervals; the maximum is ${MAX_RETENTION_INTERVALS}.`
                )
            }
            return {
                select: ['person', ...Array.from({ length: count }, (_, i) => `${period}_${i}`)],
                orderBy: ['length(appearances) DESC', 'actor_id'],
            }
        }
        default:
            throw new Error(`Unsupported source kind for actors query: ${String(sourceKind)}`)
    }
}

/**
 * Base class for the generated `query` resource: raw query execution plus the
 * wrapper semantics the generated `client.query.*` methods delegate to.
 */
export class QueryBase extends Resource {
    /**
     * Generic escape hatch: run any query node against
     * `POST /api/environments/{projectId}/query/`. The query is sent verbatim —
     * no normalization — so any `kind` the API accepts works.
     */
    async run<T = QueryResponse>(body: { query: QueryNode }, opts?: RequestOptions): Promise<T> {
        const projectId = await this.scope.projectId(opts)
        return this.http.request<T>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/query/`,
            body: { query: body.query },
            opts,
        })
    }

    /** Non-actors wrapper: `{ ...params, kind }`, normalized, POSTed to /query/. */
    protected async runWrapped<T = QueryResponse>(kind: string, params: object, opts?: RequestOptions): Promise<T> {
        const query = normalizeQuery({
            ...stripToolOnlyParams(params as Record<string, unknown>),
            kind,
        }) as QueryNode
        return this.run<T>({ query }, opts)
    }

    /**
     * Actors wrapper: builds `{ ...params, kind }` (an InsightActorsQuery /
     * FunnelsActorsQuery carrying the insight `source`), then wraps it in an
     * ActorsQuery with the per-kind projection and a 100-row page, mirroring the
     * MCP client. Returns the raw endpoint response.
     */
    protected async runActorsWrapped<T = QueryResponse>(
        kind: string,
        params: object,
        opts?: RequestOptions
    ): Promise<T> {
        const actorsQuery = normalizeQuery({ ...stripToolOnlyParams(params as Record<string, unknown>), kind })
        const { select, orderBy } = actorsProjection(actorsQuery)
        // `actor`/`person` cells carry `matched_recordings` only when requested.
        const includeRecordings = Boolean(actorsQuery.includeRecordings)
        const finalSelect = includeRecordings ? [...select, 'matched_recordings'] : select
        const wrappedQuery: QueryNode = {
            kind: 'ActorsQuery',
            source: actorsQuery,
            select: finalSelect,
            orderBy,
            limit: 100,
        }
        return this.run<T>({ query: wrappedQuery }, opts)
    }
}

/**
 * `output_format` is an MCP tool-level control, not part of the query body.
 * The generated input types omit it, but strip defensively so it can never leak
 * into the backend `kind: ...Query` payload.
 */
function stripToolOnlyParams(params: Record<string, unknown>): Record<string, unknown> {
    const { output_format: _outputFormat, ...rest } = params
    return rest
}
