import { defineNativeTool, Type } from '@posthog/agent-shared'

import { callPosthogApi, ProjectIdArg, projectPath } from './_posthog-api'

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
        'Run a HogQL query against a PostHog project as the connected user (requires `posthog` auth). Returns rows and column names. Pass the `project_id` of the project to query.',
    args: Type.Object({
        project_id: ProjectIdArg,
        query: Type.String({ minLength: 1, description: 'HogQL query string' }),
    }),
    returns: Type.Object({
        rows: Type.Array(Type.Record(Type.String(), Type.Unknown())),
        columns: Type.Array(Type.String()),
    }),
    // `query:read` is the scope the Django `QueryViewSet` enforces (`scope_object
    // = "query"`, with `create` registered as a read action). The HogQL request
    // hits `POST /api/projects/{team}/query/`.
    requires: { provider: { id: 'posthog', scopes: ['query:read'] } },
    cost_hint: 'medium',
    async run(args, ctx) {
        // Resolves the `posthog` identity (trigger-edge seed or per-asker link)
        // exactly like the sibling `@posthog/agent-applications-*` tools, so the
        // query executes AS the connected PostHog user and Django enforces that
        // user's access to `args.project_id` (a 403 surfaces as a tool error).
        const res = await callPosthogApi<HogQLQueryResponse>(ctx, {
            method: 'POST',
            path: projectPath(args.project_id, '/query/'),
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
