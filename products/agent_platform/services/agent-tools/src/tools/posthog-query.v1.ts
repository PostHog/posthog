import { defineNativeTool, Type } from '@posthog/agent-shared'

import { callPosthogApi, projectPath } from './_posthog-api'

/**
 * The slice of the Django `/query/` response we map for HogQL. The endpoint
 * returns positional rows (`results: unknown[][]`) alongside a parallel
 * `columns` list; we zip them into keyed objects so the model sees
 * `{ column: value }` rows rather than bare arrays.
 */
interface HogQLQueryResponse {
    results?: unknown[]
    columns?: string[] | null
}

export const posthogQueryV1 = defineNativeTool({
    id: '@posthog/query',
    description:
        "Run a HogQL query against the calling PostHog user's project (requires `posthog` auth). Returns rows and column names.",
    args: Type.Object({
        query: Type.String({ minLength: 1, description: 'HogQL query string' }),
    }),
    returns: Type.Object({
        rows: Type.Array(Type.Record(Type.String(), Type.Unknown())),
        columns: Type.Array(Type.String()),
    }),
    // `query:read` is the scope the Django `QueryViewSet` enforces (`scope_object
    // = "query"`, with `create` registered as a read action). The HogQL request
    // hits `POST /api/projects/{team}/query/`.
    requires: { integrations: [], scopes: ['query:read'] },
    cost_hint: 'medium',
    async run(args, ctx) {
        // Routes through the per-user credential broker (`posthog_api` bearer)
        // exactly like the sibling `@posthog/agent-applications-*` tools, so the
        // query executes AS the connected PostHog user and Django enforces that
        // user's access. `projectPath` targets the caller's team and fails
        // closed (`posthog_user_context_required`) without a `posthog` principal.
        const res = await callPosthogApi<HogQLQueryResponse>(ctx, {
            method: 'POST',
            path: projectPath(ctx, '/query/'),
            body: { query: { kind: 'HogQLQuery', query: args.query } },
        })
        const columns = res.columns ?? []
        const rows = (res.results ?? []).map((row) =>
            Array.isArray(row)
                ? Object.fromEntries(columns.map((col, i) => [col, row[i]]))
                : ((row ?? {}) as Record<string, unknown>)
        )
        ctx.log('info', 'hogql.executed', { query: args.query, row_count: rows.length })
        return { rows, columns }
    },
})
