/**
 * TabularStore — deterministic structured state for agents, as a sibling to
 * the prose MemoryStore. Where memory is "the model reads/writes markdown",
 * tables are "the model sends keys/filters and gets back computed results" —
 * the bytes never round-trip through inference. Membership tests, append-only
 * logs, dedup, and simple lookups (seen-sets, archive logs, etc.) live here.
 *
 * Storage: one JSONL object per table at
 *   <bucketPrefix>/team/<team_id>/agent/<application_slug>/tables/<name>.jsonl
 * Rows are JSON objects. The determinism lives in THIS code (Node), not in S3
 * and not in the model: each op GETs the whole object, computes in-process, and
 * conditionally PUTs back. S3 is a blob store, so whole-object read-modify-write
 * is the access pattern — fine at realistic sizes (thousands of rows = tens of
 * KB). If a table ever outgrows in-process scans, swap a `PgTabularStore` behind
 * this same interface; nothing above it changes.
 *
 * Concurrency: mutating ops use S3 ETag conditional writes (If-Match /
 * If-None-Match) with bounded retry, so racing cron firings can't lose-update.
 * Where the backend ignores conditionals it degrades to last-write-wins.
 */

import { MemoryScope } from './store'

export type TableScalar = string | number | boolean | null
export type TableRow = Record<string, unknown>

/** A column predicate. A bare scalar is shorthand for `{ eq: <scalar> }`. */
export interface TablePredicate {
    eq?: TableScalar
    in?: TableScalar[]
    gt?: number | string
    gte?: number | string
    lt?: number | string
    lte?: number | string
}

export interface TableQuery {
    /** Column → scalar (equality) or predicate. All conditions AND together. */
    where?: Record<string, TableScalar | TablePredicate>
    /** Project only these columns (omit ⇒ whole row). */
    columns?: string[]
    /** Sort by this column before limiting. */
    order_by?: string
    /** Descending order (default ascending). */
    desc?: boolean
    /** Cap the number of rows returned. */
    limit?: number
}

export interface TabularStore {
    /** List the tables that exist for this scope (cheap — names + byte size, no row GET). */
    listTables(scope: MemoryScope): Promise<{ name: string; size: number }[]>
    /**
     * Partition `values` into those already present in `keyColumn` and those
     * not. The seen-set workhorse: send N candidate ids, get back only the new
     * ones — O(1) model context regardless of table size.
     */
    membership(
        scope: MemoryScope,
        table: string,
        keyColumn: string,
        values: TableScalar[]
    ): Promise<{ known: TableScalar[]; new: TableScalar[] }>
    /**
     * Append rows. With `dedupeOn`, rows whose key already exists in the table
     * (or earlier in this same batch) are skipped. Rows missing the `dedupeOn`
     * column can't be deduped and are always appended (counted in `appended`).
     */
    append(
        scope: MemoryScope,
        table: string,
        rows: TableRow[],
        opts?: { dedupeOn?: string }
    ): Promise<{ appended: number; skipped: number }>
    /** Filter + project + order + limit. Simple predicates only. */
    query(scope: MemoryScope, table: string, q?: TableQuery): Promise<TableRow[]>
    /**
     * Like `query`, but also returns the table's total row count from the SAME
     * read — one GET instead of query()+count(). For paged views ("N of M").
     */
    queryPage(scope: MemoryScope, table: string, q?: TableQuery): Promise<{ rows: TableRow[]; total: number }>
    /** Count rows matching `where` (or all rows). */
    count(scope: MemoryScope, table: string, where?: TableQuery['where']): Promise<number>
    /** Delete rows matching `where`. Returns how many were removed. */
    delete(scope: MemoryScope, table: string, where: TableQuery['where']): Promise<{ deleted: number }>
    /** Remove the whole table object. */
    truncate(scope: MemoryScope, table: string): Promise<void>
}

const TABLE_NAME_RE = /^[a-z0-9][a-z0-9_-]*$/

/**
 * Per-table object ceiling. Whole-object read-modify-write is O(size) per op,
 * so an unbounded table degrades to quadratic over a session — cap it (mirrors
 * the memory store's per-file ceiling). Past this, the table should move to a
 * real DB backend behind the same interface.
 */
export const MAX_TABLE_BYTES = 5 * 1024 * 1024

/** Thrown by `validateTableName` on a bad name → callers map to 400. */
export class TableNameError extends Error {
    constructor(public readonly table: string) {
        super(`invalid table name "${table}" — must match ${TABLE_NAME_RE} (≤128 chars)`)
        this.name = 'TableNameError'
    }
}

/** Thrown when an append would push a table past `MAX_TABLE_BYTES`. */
export class TableTooLargeError extends Error {
    constructor(public readonly table: string) {
        super(`table "${table}" would exceed ${MAX_TABLE_BYTES} bytes — move it to a DB-backed store`)
        this.name = 'TableTooLargeError'
    }
}

export function validateTableName(name: string): string {
    if (!TABLE_NAME_RE.test(name) || name.length > 128) {
        throw new TableNameError(name)
    }
    return name
}

export function tableKeyFor(scope: MemoryScope, name: string, bucketPrefix: string): string {
    return `${tablesPrefixFor(scope, bucketPrefix)}${validateTableName(name)}.jsonl`
}

export function tablesPrefixFor(scope: MemoryScope, bucketPrefix: string): string {
    const trimmed = bucketPrefix.replace(/^\/+|\/+$/g, '')
    return `${trimmed}/team/${scope.teamId}/agent/${scope.applicationId}/tables/`
}

/** Parse JSONL into rows, skipping blank/corrupt lines (graceful degradation). */
export function parseJsonl(raw: string): TableRow[] {
    const rows: TableRow[] = []
    for (const line of raw.split('\n')) {
        const t = line.trim()
        if (!t) {
            continue
        }
        try {
            const v = JSON.parse(t)
            if (v && typeof v === 'object' && !Array.isArray(v)) {
                rows.push(v as TableRow)
            }
        } catch {
            // drop a corrupt line rather than failing the whole table
        }
    }
    return rows
}

export function serializeJsonl(rows: TableRow[]): string {
    return rows.map((r) => JSON.stringify(r)).join('\n') + (rows.length ? '\n' : '')
}

/** Parse to a finite number, or null if it isn't numeric. */
function toNum(v: unknown): number | null {
    if (typeof v === 'number') {
        return Number.isFinite(v) ? v : null
    }
    if (typeof v === 'string' && v.trim() !== '') {
        const n = Number(v)
        return Number.isFinite(n) ? n : null
    }
    return null
}

/**
 * Order two values for SORTING (`order_by`). Compares numerically when both
 * coerce to finite numbers, else lexicographically. Total order, never null —
 * sorting can't drop rows.
 */
function cmp(a: unknown, b: unknown): number {
    const na = toNum(a)
    const nb = toNum(b)
    if (na !== null && nb !== null) {
        return na - nb
    }
    return String(a).localeCompare(String(b))
}

/**
 * Compare a row value against a range PREDICATE bound. Returns the sign, or
 * `null` when the two aren't comparable — a numeric bound (incl. a numeric
 * string like `"10"`) only compares against numeric values, so `{ gt: 9 }`
 * matches `10`/`"11"` but NOT `"x"`; a non-numeric string bound compares
 * lexicographically. `null` means "doesn't satisfy the predicate".
 */
function rangeCmp(value: unknown, bound: number | string): number | null {
    const nb = toNum(bound)
    if (nb !== null) {
        const nv = toNum(value)
        return nv === null ? null : nv - nb
    }
    return String(value).localeCompare(String(bound))
}

/**
 * Evaluate one column condition against a row value. Predicates operate on
 * scalars: `in` uses value equality (objects won't match), range ops compare
 * via `cmp` (numeric when both sides are numeric, else lexicographic).
 */
function matchPredicate(value: unknown, cond: TableScalar | TablePredicate): boolean {
    if (cond === null || typeof cond !== 'object') {
        return value === cond
    }
    if ('eq' in cond && value !== cond.eq) {
        return false
    }
    if (cond.in && !cond.in.includes(value as TableScalar)) {
        return false
    }
    const ranges: [number | string | undefined, (c: number) => boolean][] = [
        [cond.gt, (c) => c > 0],
        [cond.gte, (c) => c >= 0],
        [cond.lt, (c) => c < 0],
        [cond.lte, (c) => c <= 0],
    ]
    for (const [bound, ok] of ranges) {
        if (bound === undefined) {
            continue
        }
        const c = rangeCmp(value, bound)
        if (c === null || !ok(c)) {
            return false
        }
    }
    return true
}

export function matchRow(row: TableRow, where?: TableQuery['where']): boolean {
    if (!where) {
        return true
    }
    for (const [col, cond] of Object.entries(where)) {
        if (!matchPredicate(row[col], cond)) {
            return false
        }
    }
    return true
}

/** Apply where/columns/order/limit to an in-memory row set (shared by impls). */
export function applyQuery(rows: TableRow[], q: TableQuery = {}): TableRow[] {
    let out = rows.filter((r) => matchRow(r, q.where))
    if (q.order_by) {
        const col = q.order_by
        out = [...out].sort((a, b) => cmp(a[col], b[col]))
        if (q.desc) {
            out.reverse()
        }
    }
    if (q.limit !== undefined) {
        out = out.slice(0, q.limit)
    }
    if (q.columns) {
        const cols = q.columns
        out = out.map((r) => Object.fromEntries(cols.map((c) => [c, r[c]])))
    }
    return out
}

export class TabularConflictError extends Error {
    constructor(public readonly table: string) {
        super(`tabular write conflict on "${table}" after retries`)
        this.name = 'TabularConflictError'
    }
}
