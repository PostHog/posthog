/**
 * Tabular reference tools — deterministic structured state for agents, backed
 * by the S3 JSONL TabularStore (sibling to the prose memory tools). The model
 * sends keys/filters and gets back computed results; the table bytes never
 * round-trip through inference. Scoped per (team_id, application_id).
 *
 *   table-membership — partition ids into known vs new (the seen-set workhorse)
 *   table-append     — append rows (optional dedupe on a key column)
 *   table-query      — filter + project + order + limit (simple predicates)
 *   table-count      — count rows matching a filter
 *   table-delete     — delete rows matching a filter
 *   table-truncate   — drop a whole table
 *
 * `where` is a map of column → value (equality) or a predicate object:
 *   { in: [...] } | { gt|gte|lt|lte: <number|string> }   (conditions AND together)
 *
 * Every tool accepts an optional `space` (a shared memory space slug): the op
 * runs against that space's tables instead of the agent's own, but only when the
 * agent's spec grants access — reads need a `read` grant, writes need
 * `read_write`. `teamId` is never taken from the arg, so a grant can only reach
 * spaces in the agent's own team. Omit `space` for the agent's own tables.
 */

import {
    defineNativeTool,
    TabularConflictError,
    type TableQuery,
    type TabularStore,
    type ToolContext,
    Type,
} from '@posthog/agent-shared'

import { resolveMemoryScope, SPACE } from './memory-scope'

// The TypeBox `where` schema infers as Record<string, unknown>; the store
// evaluates each condition structurally at runtime (scalar or predicate), so we
// cast at the tool boundary.
type Where = TableQuery['where']

const RESULT = Type.Object({
    ok: Type.Boolean(),
    error: Type.Optional(Type.String()),
    /** Machine-readable failure class so the model can branch (e.g. retry on
     *  `conflict`, give up on `unavailable`/`error`). */
    code: Type.Optional(Type.String()),
    data: Type.Optional(Type.Unknown()),
})

type Result<T> = { ok: true; data: T } | { ok: false; error: string; code: string }
const ok = <T>(data: T): Result<T> => ({ ok: true, data })
const err = (error: string, code = 'error'): Result<never> => ({ ok: false, error, code })

function denied(space: string | undefined): Result<never> {
    return err(`no memory access to space '${space}'`, 'access_denied')
}
function storeOrError(ctx: ToolContext): TabularStore | { error: string } {
    if (!ctx.tabularStore) {
        return { error: 'tabular_store_unavailable' }
    }
    return ctx.tabularStore
}
function asError(thrown: unknown): string {
    return (thrown as Error)?.message ?? 'unknown_error'
}
/** Classify a thrown store error for the result `code`. */
function asCode(thrown: unknown): string {
    return thrown instanceof TabularConflictError ? 'conflict' : 'error'
}

const TABLE = Type.String({ description: 'Table name (lowercase, digits, _ or -). Created on first append.' })
const SCALAR = Type.Union([Type.String(), Type.Number(), Type.Boolean(), Type.Null()])
const WHERE = Type.Record(Type.String(), Type.Unknown(), {
    description:
        'Filter map: column → value (equality), or a predicate object {in:[...]}, {gte:x}, {lte:x}, {gt:x}, {lt:x}. Conditions AND together.',
})

export const tableMembershipV1 = defineNativeTool({
    id: '@posthog/table-membership',
    approval: 'allow',
    description:
        'Partition `values` into those already present in `key_column` of the table and those not yet seen. The deterministic seen-set check: pass a batch of ids, get back only the `new` ones to process. Cheap regardless of table size; the table contents never enter your context.',
    args: Type.Object({
        table: TABLE,
        key_column: Type.String({ description: 'The column holding the identifier to test membership against.' }),
        values: Type.Array(SCALAR, { description: 'Candidate values to test.' }),
        space: SPACE,
    }),
    returns: RESULT,
    cost_hint: 'cheap',
    async run(args, ctx) {
        const s = storeOrError(ctx)
        if ('error' in s) {
            return err(s.error, 'unavailable')
        }
        const sc = resolveMemoryScope(ctx, args.space, false)
        if (!sc) {
            return denied(args.space)
        }
        try {
            const res = await s.membership(sc, args.table, args.key_column, args.values)
            return ok(res)
        } catch (e) {
            return err(asError(e), asCode(e))
        }
    },
})

export const tableAppendV1 = defineNativeTool({
    id: '@posthog/table-append',
    approval: 'allow',
    description:
        'Append rows (JSON objects) to a table, creating it if needed. With `dedupe_on`, rows whose value in that column already exists are skipped (returns counts). Use for seen-sets and append-only logs.',
    args: Type.Object({
        table: TABLE,
        rows: Type.Array(Type.Record(Type.String(), Type.Unknown()), { description: 'Rows to append.' }),
        dedupe_on: Type.Optional(
            Type.String({ description: 'Column to dedupe on; skip rows whose key already exists.' })
        ),
        space: SPACE,
    }),
    returns: RESULT,
    cost_hint: 'cheap',
    async run(args, ctx) {
        const s = storeOrError(ctx)
        if ('error' in s) {
            return err(s.error, 'unavailable')
        }
        const sc = resolveMemoryScope(ctx, args.space, true)
        if (!sc) {
            return denied(args.space)
        }
        try {
            const res = await s.append(sc, args.table, args.rows, { dedupeOn: args.dedupe_on })
            return ok(res)
        } catch (e) {
            return err(asError(e), asCode(e))
        }
    },
})

export const tableQueryV1 = defineNativeTool({
    id: '@posthog/table-query',
    approval: 'allow',
    description:
        'Read rows from a table, filtered by `where`, optionally projected to `columns`, ordered, and limited. Returns the matching rows.',
    args: Type.Object({
        table: TABLE,
        where: Type.Optional(WHERE),
        columns: Type.Optional(Type.Array(Type.String(), { description: 'Project only these columns.' })),
        order_by: Type.Optional(Type.String({ description: 'Sort by this column.' })),
        desc: Type.Optional(Type.Boolean({ description: 'Descending order.' })),
        limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 1000 })),
        space: SPACE,
    }),
    returns: RESULT,
    cost_hint: 'cheap',
    async run(args, ctx) {
        const s = storeOrError(ctx)
        if ('error' in s) {
            return err(s.error, 'unavailable')
        }
        const sc = resolveMemoryScope(ctx, args.space, false)
        if (!sc) {
            return denied(args.space)
        }
        try {
            const rows = await s.query(sc, args.table, {
                where: args.where as Where,
                columns: args.columns,
                order_by: args.order_by,
                desc: args.desc,
                limit: args.limit,
            })
            return ok({ count: rows.length, rows })
        } catch (e) {
            return err(asError(e), asCode(e))
        }
    },
})

export const tableCountV1 = defineNativeTool({
    id: '@posthog/table-count',
    approval: 'allow',
    description: 'Count rows in a table matching `where` (or all rows if omitted).',
    args: Type.Object({ table: TABLE, where: Type.Optional(WHERE), space: SPACE }),
    returns: RESULT,
    cost_hint: 'cheap',
    async run(args, ctx) {
        const s = storeOrError(ctx)
        if ('error' in s) {
            return err(s.error, 'unavailable')
        }
        const sc = resolveMemoryScope(ctx, args.space, false)
        if (!sc) {
            return denied(args.space)
        }
        try {
            return ok({ count: await s.count(sc, args.table, args.where as Where) })
        } catch (e) {
            return err(asError(e), asCode(e))
        }
    },
})

export const tableDeleteV1 = defineNativeTool({
    id: '@posthog/table-delete',
    approval: 'allow',
    description: 'Delete rows from a table matching `where` (required). Returns how many were removed.',
    args: Type.Object({ table: TABLE, where: WHERE, space: SPACE }),
    returns: RESULT,
    cost_hint: 'cheap',
    async run(args, ctx) {
        const s = storeOrError(ctx)
        if ('error' in s) {
            return err(s.error, 'unavailable')
        }
        const sc = resolveMemoryScope(ctx, args.space, true)
        if (!sc) {
            return denied(args.space)
        }
        try {
            return ok(await s.delete(sc, args.table, args.where as Where))
        } catch (e) {
            return err(asError(e), asCode(e))
        }
    },
})

export const tableTruncateV1 = defineNativeTool({
    id: '@posthog/table-truncate',
    approval: 'allow',
    description: 'Remove an entire table (all rows). Use to reset state.',
    args: Type.Object({ table: TABLE, space: SPACE }),
    returns: RESULT,
    cost_hint: 'cheap',
    async run(args, ctx) {
        const s = storeOrError(ctx)
        if ('error' in s) {
            return err(s.error, 'unavailable')
        }
        const sc = resolveMemoryScope(ctx, args.space, true)
        if (!sc) {
            return denied(args.space)
        }
        try {
            await s.truncate(sc, args.table)
            return ok({ truncated: args.table })
        } catch (e) {
            return err(asError(e), asCode(e))
        }
    },
})
